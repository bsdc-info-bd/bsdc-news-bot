def format_article_images(title, ai_html, image_urls):
    if not image_urls:
        return None, ""

    main_img = image_urls[0]
    sec_img = image_urls[1] if len(image_urls) > 1 else ""

    if sec_img:
        sec_img_html = f'''
        <figure style="margin: 30px 0; text-align: center;">
            <img src="{sec_img}" loading="lazy" style="max-width:100%; height:auto; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.1);" alt="{title} overview">
            <figcaption style="font-size:13px; color:#64748b; margin-top:8px; font-family:sans-serif;">Key highlight relating to {title}</figcaption>
        </figure>
        '''
        parts = ai_html.split("</h2>", 1)
        if len(parts) > 1:
            ai_html = parts[0] + "</h2>" + sec_img_html + parts[1]

    hero_html = f'''
    <div style="text-align:center; margin-bottom:25px;">
        <img src="{main_img}" loading="eager" style="max-width:100%; height:auto; border-radius:12px; box-shadow:0 6px 18px rgba(0,0,0,0.12);" alt="{title}">
    </div>
    '''
    return main_img, hero_html + ai_html
