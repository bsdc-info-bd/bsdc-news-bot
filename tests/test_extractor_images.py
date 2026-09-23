import struct

from bsdc_news.extractor import ImageCandidate, parse_article, score_image
from bsdc_news.images import ImagePicker, figure_html, image_size, proxied

from .conftest import FakeHttp, PNG_1600x900


def test_parse_article_text_metadata_and_images(article_html):
    art = parse_article(article_html, "https://example-tech.com/2026/09/22/nvidia-rubin-ultra/")
    assert art.words > 300
    assert "Rubin Ultra" in art.text
    assert "Subscribe to our newsletter" not in art.text
    assert art.author == "Jane Doe"
    assert art.published.startswith("2026-09-22")
    assert art.sitename == "Example Tech"
    assert art.canonical == "https://example-tech.com/2026/09/22/nvidia-rubin-ultra/"
    assert not art.paywalled
    urls = [c.url for c in art.images]
    # og:image resolved to an absolute URL and ranked first
    assert urls[0] == "https://example-tech.com/images/2026/09/rubin-ultra-hero.jpg"
    assert "https://cdn.example-tech.com/rubin-ultra-board.jpg" in urls  # lazy data-src resolved
    assert "https://cdn.example-tech.com/huang-keynote-1600.jpg" in urls  # largest srcset candidate
    assert not any("logo" in u or "avatar" in u or "ads." in u for u in urls)
    board = next(c for c in art.images if "board" in c.url)
    assert "Rubin Ultra board" in (board.caption or board.alt)


def test_image_size_sniffing_png_gif_jpeg_webp():
    assert image_size(PNG_1600x900) == (1600, 900)
    gif = b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 20
    assert image_size(gif) == (640, 480)
    jpeg = (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 +
            b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 720, 1280) + b"\x00" * 20)
    assert image_size(jpeg) == (1280, 720)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8 + (1199).to_bytes(3, "little") + (674).to_bytes(3, "little")
    assert image_size(webp) == (1200, 675)
    assert image_size(b"not an image at all, sorry!!") is None


def test_image_picker_verifies_and_rejects_small_or_broken(settings):
    settings.offline = False
    http = FakeHttp()
    picker = ImagePicker(http, settings)
    cands = [ImageCandidate(url="https://x.com/avatar.jpg", origin="og"),
             ImageCandidate(url="https://x.com/hero.jpg", origin="og")]
    for c in cands:
        c.score = score_image(c)
    chosen = picker.select(cands, feed_image="https://x.com/feed.jpg")
    assert [c.url for c in chosen][:1] == ["https://x.com/hero.jpg"]
    assert chosen[0].width == 1600 and chosen[0].height == 900


def test_proxy_and_figure_are_escaped():
    url = proxied("https://cdn.site.com/a b.jpg?x=1&y=2", 800)
    assert url.startswith("https://wsrv.nl/?url=https%3A%2F%2Fcdn.site.com") and "w=800" in url
    assert proxied(url) == url  # idempotent
    html = figure_html('https://x.com/i.jpg"onerror="alert(1)', alt='A "quoted" <title>', caption="Cap & more")
    assert 'onerror="alert' not in html and "&quot;quoted&quot;" in html and "&lt;title&gt;" in html


def test_openverse_offline_returns_nothing(settings):
    picker = ImagePicker(FakeHttp(), settings)
    assert picker.openverse("nvidia chip") == []


def test_junk_filter_uses_tokens_not_substrings():
    from bsdc_news.extractor import _is_junk

    assert _is_junk("https://x.com/wp-content/uploads/author/jane.jpg")
    assert _is_junk("https://x.com/static/logo-dark.png")
    assert _is_junk("https://ads.x.com/ads/banner.jpg")
    assert _is_junk("https://x.com/img/photo.jpg?w=40")
    assert not _is_junk("https://x.com/2026/09/social-media-ban-australia.jpg")
    assert not _is_junk("https://x.com/2026/09/downloading-app-store.jpg")
    assert not _is_junk("https://x.com/2026/09/shareholders-meeting.jpg?w=1600")


def test_openverse_credit_links_licence_and_source():
    html = figure_html("https://img/x.jpg", alt="x", credit="Jane / CC BY 4.0 via Openverse",
                       license_url="https://creativecommons.org/licenses/by/4.0/", source_page="https://flickr.com/p/1")
    assert 'href="https://flickr.com/p/1"' in html and 'href="https://creativecommons.org/licenses/by/4.0/"' in html
