"""Backward-compatible Blogger helpers (v5 API).

Fixes: the schema ``@context`` had been pasted as a Markdown link (``[url](url)``)
instead of a plain URL; ``datetime.utcnow`` is deprecated; titles were not escaped.
"""

from bsdc_news.content.seo import jsonld_tag, news_article_schema
from bsdc_news.settings import load_settings
from bsdc_news.utils import esc, iso


def get_blogger_service():
    from bsdc_news.blogger import BloggerClient

    s = load_settings()
    return BloggerClient(s.secret("blog_id"), s.secret("google_client_id"), s.secret("google_client_secret"),
                         s.secret("google_refresh_token")).service()


def compose_google_news_schema(title, main_img):
    return jsonld_tag(news_article_schema(headline=title, description=title, images=[main_img] if main_img else [],
                                          published=iso(), site_name="bsdc news"))


def build_final_html(title, body_html, main_img, source_name, source_url):
    return (f"{compose_google_news_schema(title, main_img)}"
            f'<div style="font-size:17px;line-height:1.85;color:#1e293b;font-family:Georgia,serif;">{body_html}</div>'
            f'<hr style="border:0;border-top:1px solid #e2e8f0;margin:35px 0;">'
            f'<p style="font-size:12px;color:#94a3b8;font-family:sans-serif;">Source: {esc(source_name)} | '
            f'<a href="{esc(source_url)}" target="_blank" rel="nofollow noopener noreferrer" '
            f'style="color:#94a3b8;text-decoration:underline;">Original Article</a></p>')
