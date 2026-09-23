"""Backward-compatible image formatting helper (v5 API) — now HTML-escaped."""

from bsdc_news.images import figure_html


def format_article_images(title, ai_html, image_urls):
    if not image_urls:
        return None, ai_html or ""
    main_img = image_urls[0]
    body = ai_html or ""
    if len(image_urls) > 1:
        inline = figure_html(image_urls[1], alt=f"{title} — detail")
        parts = body.split("</h2>", 1)
        body = parts[0] + "</h2>" + inline + parts[1] if len(parts) > 1 else body + inline
    return main_img, figure_html(main_img, alt=title, eager=True) + body
