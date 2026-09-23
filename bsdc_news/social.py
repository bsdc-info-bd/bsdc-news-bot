"""Free social distribution of new posts: Telegram channel, Facebook Page,
Mastodon and Bluesky.  Every network is optional and isolated."""

from __future__ import annotations

from datetime import UTC, datetime

from .http import HttpClient
from .log import get_logger
from .utils import truncate

log = get_logger("social")


def hashtags(labels: list[str], limit: int = 3) -> str:
    tags = []
    for label in labels:
        tag = "".join(ch for ch in label.title() if ch.isalnum())
        if tag and tag.lower() not in ("technews",) and len(tag) <= 24:
            tags.append("#" + tag)
    return " ".join(tags[:limit])


class SocialPoster:
    def __init__(self, settings, http: HttpClient) -> None:
        self.s = settings
        self.http = http
        self.results: dict[str, list[str]] = {}

    def _ok(self, network: str, url: str) -> None:
        self.results.setdefault(network, []).append(url)

    def share(self, title: str, url: str, summary: str, labels: list[str], image: str = "") -> None:
        tags = hashtags(labels)
        for fn in (self.telegram_channel, self.facebook, self.mastodon, self.bluesky):
            try:
                fn(title, url, summary, tags, image)
            except Exception as exc:  # never break publishing because of social
                log.warning("Social share (%s) failed: %s", fn.__name__, exc)

    def telegram_channel(self, title, url, summary, tags, image) -> None:
        token, chat = self.s.secret("telegram_bot_token"), self.s.secret("telegram_channel_id")
        if not (token and chat and self.s.get("social.telegram_channel_post", True)):
            return
        caption = f"<b>{_esc(title)}</b>\n\n{_esc(truncate(summary, 600))}\n\n{tags}\n🔗 {url}"
        if image:
            resp = self.http.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                                  json={"chat_id": chat, "photo": image, "caption": caption[:1020],
                                        "parse_mode": "HTML"}, timeout=20)
            if resp.status_code < 300:
                return self._ok("telegram", url)
        resp = self.http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": caption, "parse_mode": "HTML"}, timeout=20)
        if resp.status_code < 300:
            self._ok("telegram", url)

    def facebook(self, title, url, summary, tags, image) -> None:
        page, token = self.s.secret("facebook_page_id"), self.s.secret("facebook_page_token")
        if not (page and token and self.s.get("social.facebook_page", True)):
            return
        resp = self.http.post(f"https://graph.facebook.com/v23.0/{page}/feed",
                              data={"message": f"{title}\n\n{truncate(summary, 400)}\n\n{tags}", "link": url,
                                    "access_token": token}, timeout=20)
        if resp.status_code < 300:
            self._ok("facebook", url)
        else:
            log.warning("Facebook HTTP %s: %s", resp.status_code, resp.text[:150])

    def mastodon(self, title, url, summary, tags, image) -> None:
        base, token = self.s.secret("mastodon_base_url"), self.s.secret("mastodon_token")
        if not (base and token and self.s.get("social.mastodon", True)):
            return
        status = f"{title}\n\n{truncate(summary, 280)}\n\n{tags}\n{url}"[:490]
        resp = self.http.post(f"{base.rstrip('/')}/api/v1/statuses", headers={"Authorization": f"Bearer {token}"},
                              data={"status": status, "visibility": "public", "language": "en"}, timeout=20)
        if resp.status_code < 300:
            self._ok("mastodon", url)

    def bluesky(self, title, url, summary, tags, image) -> None:
        handle, password = self.s.secret("bluesky_handle"), self.s.secret("bluesky_app_password")
        if not (handle and password and self.s.get("social.bluesky", True)):
            return
        auth = self.http.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                              json={"identifier": handle, "password": password}, timeout=20)
        if auth.status_code != 200:
            log.warning("Bluesky login failed: HTTP %s", auth.status_code)
            return
        session = auth.json()
        text = truncate(f"{title}\n\n{url}", 300)
        start = len(text.encode("utf-8")) - len(url.encode("utf-8"))
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "langs": ["en"],
            "embed": {"$type": "app.bsky.embed.external",
                      "external": {"uri": url, "title": truncate(title, 200), "description": truncate(summary, 280)}},
        }
        if text.endswith(url):
            record["facets"] = [{"index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
                                 "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]}]
        resp = self.http.post("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                              headers={"Authorization": f"Bearer {session['accessJwt']}"},
                              json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
                              timeout=20)
        if resp.status_code < 300:
            self._ok("bluesky", url)


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
