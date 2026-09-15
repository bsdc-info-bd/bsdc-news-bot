import os
import sys
import time
import json
import re
import concurrent.futures
from datetime import datetime

import feedparser
import requests
import cloudscraper
import trafilatura
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from colorama import init, Fore, Style

from google import genai
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

init(autoreset=True)

# ---------------------------------------------------------
# SECRETS & ENV CONFIG
# ---------------------------------------------------------
BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
INDEXING_JSON = os.environ.get("INDEXING_SERVICE_ACCOUNT_JSON", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if not all([BLOG_ID, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, GEMINI_KEY]):
    print(Fore.RED + "❌ ERROR: Missing GitHub Secrets (Check BLOG_ID, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, GEMINI_API_KEY).")
    sys.exit(1)

# Initialize Gemini AI Client
ai_client = genai.Client(api_key=GEMINI_KEY)

RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://www.engadget.com/rss.xml",
    "https://www.zdnet.com/news/rss.xml"
]

# ---------------------------------------------------------
# GOOGLE & BING SERVICE INITIALIZERS
# ---------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_blogger_service():
    creds = Credentials(None, refresh_token=REFRESH_TOKEN, client_id=CLIENT_ID,
                        client_secret=CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return build("blogger", "v3", credentials=creds)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_indexing_service():
    if not INDEXING_JSON: return None
    info = json.loads(INDEXING_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/indexing"])
    return build('indexing', 'v3', credentials=creds)

# ---------------------------------------------------------
# AI REWRITER & SEO FORMATTER
# ---------------------------------------------------------
def rewrite_with_ai(title, raw_text):
    """Uses Gemini AI to restructure raw text into 600+ word Google News HTML article."""
    prompt = f"""
    You are a senior tech journalist for 'bsdc news'. Rewrite the following article into a professional, highly engaging, 600+ word news article optimized for Google News.

    STRICT RULES:
    1. Output ONLY clean HTML tags (<p>, <h2>, <h3>, <ul>, <li>, <strong>, <mark>). Do NOT include <html>, <head>, <body>, or Markdown ```html blocks.
    2. Fix all broken sentences, weird line breaks, and bad formatting.
    3. REMOVE all inline links, source promotion, and original author bios from the content.
    4. Structure the text with 2-3 clear <h2> subheadings and key takeaways using bullet points or <mark> highlight tags.
    5. Maintain a professional, objective, and authoritative tone suitable for Google News.

    Original Title: {title}
    Raw Content:
    {raw_text[:4000]}
    """
    
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        cleaned_html = response.text.replace("```html", "").replace("```", "").strip()
        return cleaned_html
    except Exception as e:
        print(Fore.RED + f"   ⚠️ AI Generation failed: {e}")
        return None

# ---------------------------------------------------------
# CONTENT EXTRACTION & IMAGE PARSER
# ---------------------------------------------------------
def scrape_full_article(entry_url):
    scraper = cloudscraper.create_scraper()
    try:
        res = scraper.get(entry_url, timeout=12)
        if res.status_code != 200: return None, []
        
        soup = BeautifulSoup(res.text, 'html.parser')
        image_urls = []
        
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('srcset')
            if src and src.startswith('http') and not any(bad in src.lower() for bad in ['avatar', 'logo', 'icon', 'tracker', 'ad-']):
                image_urls.append(src.split(' ')[0])
                
        image_urls = list(dict.fromkeys(image_urls))
        raw_text = trafilatura.extract(res.text)
        
        return raw_text, image_urls
    except Exception:
        return None, []

def build_google_news_post(title, ai_html, image_urls, source_name, source_url):
    main_image = image_urls[0]
    secondary_image = image_urls[1] if len(image_urls) > 1 else ""

    # Embed secondary image inside content
    if secondary_image:
        sec_img_block = f'<div style="text-align:center; margin: 30px 0;"><img src="{secondary_image}" style="max-width:100%; height:auto; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.1);" alt="{title} image"></div>'
        parts = ai_html.split("</h2>", 1)
        if len(parts) > 1:
            ai_html = parts[0] + "</h2>" + sec_img_block + parts[1]

    # Google News Article Schema
    schema = {
        "@context": "[https://schema.org](https://schema.org)",
        "@type": "NewsArticle",
        "headline": title,
        "image": [main_image],
        "datePublished": datetime.utcnow().isoformat() + "Z",
        "author": {"@type": "Organization", "name": "bsdc news"},
        "publisher": {"@type": "Organization", "name": "bsdc news"},
        "description": title
    }

    seo_footer = """
    <div style="margin-top: 45px; padding: 25px; background: #f8fafc; border-left: 5px solid #2563eb; border-radius: 8px; font-family: sans-serif;">
        <h3 style="margin-top:0; color:#1e293b; font-size: 20px; font-weight:700;">About bsdc news</h3>
        <p style="color:#475569; font-size:15px; line-height:1.7; margin-bottom:0;">
            <strong>bsdc news</strong> delivers high-authority real-time tech intelligence, web engineering insights, and digital break-throughs updated 24/7.
        </p>
    </div>
    """

    final_content = f"""
    <script type="application/ld+json">{json.dumps(schema)}</script>
    <div style="text-align:center; margin-bottom:25px;">
        <img src="{main_image}" style="max-width:100%; height:auto; border-radius:12px; box-shadow:0 6px 18px rgba(0,0,0,0.12);" alt="{title}">
    </div>
    <div style="font-size:17px; line-height:1.85; color:#1e293b; font-family:Georgia, serif;">
        {ai_html}
    </div>
    <hr style="border:0; border-top:1px solid #e2e8f0; margin:35px 0;">
    <p style="font-size:12px; color:#94a3b8; font-family:sans-serif;">
        Source: {source_name} | <a href="{source_url}" target="_blank" rel="nofollow noopener noreferrer" style="color:#94a3b8; text-decoration:underline;">Original Report</a>
    </p>
    {seo_footer}
    """
    return final_content

# ---------------------------------------------------------
# INSTANT INDEXING ENGINE
# ---------------------------------------------------------
def execute_indexing_engine(urls):
    if not urls: return
    print(Fore.CYAN + f"\n⚡ Launching Instant Indexing Engine on {len(urls)} URLs...")
    
    # 1. Google Indexing API
    g_service = get_indexing_service()
    if g_service:
        for url in urls:
            try:
                g_service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
                print(Fore.GREEN + f"   [Google Indexing API] Pushed: {url}")
            except Exception as e:
                print(Fore.RED + f"   [Google Indexing API] Error: {e}")

    # 2. Bing / IndexNow Protocol
    try:
        domain = urls[0].split('/')[2]
        payload = {
            "host": domain,
            "key": "bsdcnewsindexnowkey123",
            "keyLocation": f"https://{domain}/bsdcnewsindexnowkey123.txt",
            "urlList": urls
        }
        res = requests.post("[https://api.indexnow.org/indexnow](https://api.indexnow.org/indexnow)", json=payload, timeout=10)
        if res.status_code in [200, 202]:
            print(Fore.GREEN + f"   [IndexNow] Pushed {len(urls)} URLs to Bing/Yandex.")
    except Exception as e:
        print(Fore.RED + f"   [IndexNow] Error: {e}")

# ---------------------------------------------------------
# MAIN AUTOMATION CONTROLLER
# ---------------------------------------------------------
def main():
    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")
    print(Fore.MAGENTA + Style.BRIGHT + "🚀 bsdc news 4.0 - AI Engine Active")
    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")

    blogger = get_blogger_service()
    
    # Existing titles & URLs
    posts_res = blogger.posts().list(blogId=BLOG_ID, maxResults=50).execute()
    items = posts_res.get('items', [])
    existing_titles = {p.get('title', '') for p in items}
    existing_urls = [p.get('url') for p in items if p.get('url')]

    published_urls = []
    
    for feed_url in RSS_FEEDS:
        if len(published_urls) >= 5: break
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get('title', 'Tech News')
            
            for entry in feed.entries:
                if len(published_urls) >= 5: break
                if entry.title in existing_titles: continue

                print(Fore.YELLOW + f"🔎 Scraping: '{entry.title[:50]}...'")
                raw_text, image_urls = scrape_full_article(entry.link)

                # STRICT RULE: Skip if no images or insufficient text
                if not image_urls or not raw_text or len(raw_text.split()) < 250:
                    print(Fore.RED + "   ⚠️ Skipped: Missing high-quality images or insufficient body text.")
                    continue

                print(Fore.BLUE + "   🤖 Generating AI Google News Article...")
                ai_html = rewrite_with_ai(entry.title, raw_text)
                if not ai_html: continue

                final_post_html = build_google_news_post(
                    title=entry.title,
                    ai_html=ai_html,
                    image_urls=image_urls,
                    source_name=source_name,
                    source_url=entry.link
                )

                # Publish to Blogger
                body = {
                    "title": entry.title,
                    "content": final_post_html,
                    "labels": ["Tech News", "Google News", "Technology"]
                }
                res = blogger.posts().insert(blogId=BLOG_ID, body=body).execute()
                post_url = res.get('url')
                
                if post_url:
                    published_urls.append(post_url)
                    existing_titles.add(entry.title)
                    print(Fore.GREEN + f"   🎉 Published: {post_url}")
                
                time.sleep(2)
        except Exception as e:
            print(Fore.RED + f"⚠️ Feed error ({feed_url}): {e}")

    # Trigger Instant Indexing Engine on new posts + backfill top 15 existing posts
    all_target_urls = list(set(published_urls + existing_urls[:15]))
    execute_indexing_engine(all_target_urls)

    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")
    print(Fore.MAGENTA + Style.BRIGHT + "🏆 bsdc news 4.0 Execution Complete.")
    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")

if __name__ == "__main__":
    main()
