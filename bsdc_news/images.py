"""Image pipeline: dimension sniffing (pure Python, no Pillow), validation,
open-licence fallback (Openverse) and free CDN delivery (wsrv.nl)."""

from __future__ import annotations

import struct
from urllib.parse import quote

from .extractor import ImageCandidate, score_image
from .http import HttpClient
from .log import get_logger
from .utils import esc

log = get_logger("images")

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
WSRV = "https://wsrv.nl/?url={url}&w={w}&output=webp&q=82&we&default={url}"  # default = original on failure


def image_size(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) from the first bytes of a PNG/JPEG/GIF/WebP/AVIF file."""
    if len(data) < 26:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L" and len(data) >= 25:
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return w, h
        if chunk == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + seg_len
        return None
    if data[4:8] == b"ftyp" and (b"avif" in data[8:32] or b"heic" in data[8:32]):
        idx = data.find(b"ispe")
        if idx != -1 and idx + 16 <= len(data):
            w, h = struct.unpack(">II", data[idx + 8:idx + 16])
            return w, h
    return None


def proxied(url: str, width: int = 1200) -> str:
    """Serve an image through the free wsrv.nl image CDN (resized, WebP, cached)."""
    if not url or url.startswith("https://wsrv.nl/"):
        return url
    return WSRV.format(url=quote(url, safe=""), w=int(width))


class ImagePicker:
    def __init__(self, http: HttpClient, settings) -> None:
        self.http = http
        self.min_width = int(settings.get("extraction.min_image_width", 480))
        self.max_images = int(settings.get("extraction.max_images", 4))
        self.check_dimensions = bool(settings.get("images.check_dimensions", True))
        self.use_openverse = bool(settings.get("images.openverse_fallback", True))
        self.use_proxy = bool(settings.get("images.proxy", True))
        self.proxy_width = int(settings.get("images.proxy_width", 1200))
        self.offline = bool(getattr(settings, "offline", False))
        self.openverse_id = settings.secret("openverse_client_id") if hasattr(settings, "secret") else ""
        self.openverse_secret = settings.secret("openverse_client_secret") if hasattr(settings, "secret") else ""

    def verify(self, cand: ImageCandidate) -> bool:
        """Download the first bytes, confirm it is a real image and big enough."""
        if self.offline or not self.check_dimensions:
            return True
        try:
            status, headers, data = self.http.get_bytes(cand.url, limit=65536, timeout=10)
        except Exception as exc:
            log.debug("image check failed %s: %s", cand.url, exc)
            return False
        if status not in (200, 206):
            return False
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        if ctype and not ctype.startswith("image/"):
            return False
        size = image_size(data)
        if size:
            cand.width, cand.height = size
        elif not cand.width:
            return "svg" not in ctype  # unknown format but served as an image
        if cand.width and cand.width < self.min_width:
            return False
        if cand.width and cand.height:
            ratio = cand.width / max(1, cand.height)
            if ratio < 0.5 or ratio > 3.5:
                return False
        cand.score = score_image(cand)
        return True

    def select(self, candidates: list[ImageCandidate], feed_image: str = "") -> list[ImageCandidate]:
        pool = list(candidates)
        if feed_image and all(c.url != feed_image for c in pool):
            pool.append(ImageCandidate(url=feed_image, origin="feed"))
            pool[-1].score = score_image(pool[-1])
        pool.sort(key=lambda c: c.score, reverse=True)
        chosen: list[ImageCandidate] = []
        for cand in pool[:10]:  # never download more than 10 image headers per article
            if len(chosen) >= self.max_images:
                break
            if self.verify(cand):
                chosen.append(cand)
        return chosen

    def openverse(self, query: str, limit: int = 1) -> list[ImageCandidate]:
        """Free, openly licensed images (CC0 / CC BY / CC BY-SA) as a fallback hero image."""
        if not self.use_openverse or self.offline or not query:
            return []
        params = {"q": query[:120], "license_type": "commercial", "page_size": 8,
                  "mature": "false", "aspect_ratio": "wide", "size": "large"}
        headers = {}
        token = self._openverse_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = self.http.get(OPENVERSE_URL, params=params, headers=headers, timeout=15, api=True)
            if resp.status_code != 200:
                log.debug("Openverse HTTP %s", resp.status_code)
                return []
            results = resp.json().get("results", [])
        except Exception as exc:
            log.debug("Openverse failed: %s", exc)
            return []
        out: list[ImageCandidate] = []
        for r in results:
            url = r.get("url")
            if not url or (r.get("width") or 0) < self.min_width:
                continue
            license_code = str(r.get("license", "")).upper()
            version = r.get("license_version") or ""
            cand = ImageCandidate(
                url=url, origin="openverse", width=int(r.get("width") or 0), height=int(r.get("height") or 0),
                alt=(r.get("title") or query)[:150], creator=r.get("creator") or "",
                license=f"CC {license_code} {version}".strip() if license_code not in ("CC0", "PDM") else license_code,
                license_url=r.get("license_url") or "", source_page=r.get("foreign_landing_url") or "",
            )
            cand.credit = f"{cand.creator or 'Unknown'} / {cand.license} via Openverse"
            cand.score = score_image(cand)
            out.append(cand)
            if len(out) >= limit:
                break
        return out

    def _openverse_token(self) -> str:
        if not (self.openverse_id and self.openverse_secret):
            return ""
        try:
            resp = self.http.post("https://api.openverse.org/v1/auth_tokens/token/", data={
                "client_id": self.openverse_id, "client_secret": self.openverse_secret,
                "grant_type": "client_credentials"}, timeout=10)
            return resp.json().get("access_token", "") if resp.status_code == 200 else ""
        except Exception:
            return ""

    def display_url(self, cand: ImageCandidate, width: int | None = None) -> str:
        return proxied(cand.url, width or self.proxy_width) if self.use_proxy else cand.url


def figure_html(src: str, alt: str, caption: str = "", credit: str = "", eager: bool = False,
                width: int = 0, height: int = 0, license_url: str = "", source_page: str = "") -> str:
    dims = f' width="{width}" height="{height}"' if width and height else ""
    loading = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy" decoding="async"'
    cap_bits = [esc(caption)] if caption else []
    if credit:
        credit_html = esc(credit)
        if source_page:
            credit_html = f'<a href="{esc(source_page)}" rel="nofollow noopener" target="_blank">{credit_html}</a>'
        if license_url:
            credit_html += f' (<a href="{esc(license_url)}" rel="nofollow noopener" target="_blank">licence</a>)'
        cap_bits.append(f'<span style="opacity:.8">Image: {credit_html}</span>')
    cap = (f'<figcaption style="font-size:13px;color:#64748b;margin-top:8px;font-family:sans-serif;">'
           f'{" · ".join(cap_bits)}</figcaption>') if cap_bits else ""
    return (f'<figure style="margin:28px 0;text-align:center;">'
            f'<img src="{esc(src)}" alt="{esc(alt)}"{dims} {loading} '
            f'style="max-width:100%;height:auto;border-radius:12px;box-shadow:0 6px 18px rgba(0,0,0,.12);">'
            f'{cap}</figure>')
