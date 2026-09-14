import os
import sys
import time
import json
import re
import math
import concurrent.futures
from datetime import datetime

# Advanced Data & Scraping
import feedparser
import requests
import cloudscraper
import trafilatura
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

# NLP & Sanitization
import yake
import bleach

# Resilience & Styling
from tenacity import retry, stop_after_attempt, wait_exponential
from colorama import init, Fore, Style

# Google API
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

init(autoreset=True)

# ---------------------------------------------------------
# CONFIGURATION & SECRETS
# ---------------------------------------------------------
BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
INDEXING_JSON = os.environ.get("INDEXING_SERVICE_ACCOUNT_JSON", "").strip()

if not all([BLOG_ID, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    print(Fore.RED + "❌ CRITICAL ERROR: Missing GitHub Secrets. Halting execution.")
    sys.exit(1)

# Massive list of High-Authority Tech Sources
RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://www.engadget.com/rss.xml",
    "https://www.zdnet.com/news/rss.xml",
    "https://gizmodo.com/feed",
    "https://mashable.com/feeds/rss/all",
    "https://venturebeat.com/feed/",
    "https://thenextweb.com/feed/"
]

# ---------------------------------------------------------
# CORE SERVICES & RETRY LOGIC (NO ERRORS)
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

def get_scraper():
    """Returns a Cloudflare-bypassing scraper with dynamic user agents."""
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    scraper.headers.update({'User-Agent': UserAgent().random})
    return scraper

# ---------------------------------------------------------
# NLP & SEO MODULES
# ---------------------------------------------------------
def generate_seo_tags(text, max_tags=5):
    """Uses YAKE NLP to read the article and automatically generate accurate SEO labels."""
    try:
        kw_extractor = yake.KeywordExtractor(lan="en", n=2, dedupLim=0.9, top=max_tags, features=None)
        keywords = kw_extractor.extract_keywords(text)
        tags = [kw[0].title() for kw in keywords]
        tags.extend(["Tech News", "Technology", "bsdc news"])
        return list(set(tags))[:8] # Return max 8 tags
    except:
        return ["Tech News", "Technology", "WebDev", "bsdc news"]

def calculate_reading_time(word_count):
    minutes = math.ceil(word_count / 220)
    return f"{minutes} min read"

# ---------------------------------------------------------
# CONTENT EXTRACTION ENGINE
# ---------------------------------------------------------
def process_single_article(entry, source_name, existing_titles):
    """Deep scrapes an article, validates constraints, and builds HTML."""
    if entry.title in existing_titles:
        return None
        
    scraper = get_scraper()
    try:
        response = scraper.get(entry.link, timeout=15)
        if response.status_code != 200: return None
        html_content = response.text
        
        # Extract pure text
        extracted_text = trafilatura.extract(html_content, include_links=True)
        if not extracted_text: return None
        
        word_count = len(extracted_text.split())
        if word_count < 500:
            return None # STRICT: Drop articles under 500 words
            
        # Extract images
        soup = BeautifulSoup(html_content, 'html.parser')
        image_urls = []
        for img in soup.find_all(['img', 'picture']):
            src = img.get('src') or img.get('data-src') or img.get('srcset')
            if src and src.startswith('http') and not any(x in src.lower() for x in ['avatar', 'logo', 'icon', 'tracker']):
                image_urls.append(src.split(' ')[0])
                
        image_urls = list(dict.fromkeys(image_urls))
        if not image_urls:
            return None # STRICT: Drop articles with no images
            
        # NLP SEO tags
        seo_tags = generate_seo_tags(extracted_text)
        reading_time = calculate_reading_time(word_count)
        
        formatted_html = build_ultra_seo_html(
            title=entry.title,
            text=extracted_text,
            images=image_urls,
            source_name=source_name,
            source_url=entry.link,
            read_time=reading_time
        )
        
        return {
            "title": entry.title,
            "content": formatted_html,
            "labels": seo_tags
        }
    except Exception as e:
        return None

def build_ultra_seo_html(title, text, images, source_name, source_url, read_time):
    main_image = images[0]
    secondary_image = images[1] if len(images) > 1 else ""
    
    # Sanitize and structure paragraphs
    clean_text = bleach.clean(text, tags=['p', 'b', 'i', 'u', 'a', 'h2', 'h3'], strip=True)
    paragraphs = [f"<p style='margin-bottom: 20px;'>{p.strip()}</p>" for p in clean_text.split('\n\n') if len(p.strip()) > 30]
    
    if secondary_image and len(paragraphs) > 4:
        paragraphs.insert(len(paragraphs)//2, f'<div style="margin: 30px 0;"><img src="{secondary_image}" style="width:100%; border-radius:10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);" alt="{title} image 2"></div>')

    body_html = "".join(paragraphs)
    
    # JSON-LD Schema
    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "mainEntityOfPage": {"@type": "WebPage", "@id": source_url},
        "headline": title,
        "image": [main_image],
        "datePublished": datetime.utcnow().isoformat() + "Z",
        "author": {"@type": "Organization", "name": "bsdc news automated"},
        "publisher": {"@type": "Organization", "name": "bsdc news", "logo": {"@type": "ImageObject", "url": main_image}},
        "description": clean_text[:200]
    }

    bsdc_seo_footer = f"""
    <div style="background: linear-gradient(145deg, #f0f4f8, #d9e2ec); border-left: 6px solid #102a43; padding: 30px; border-radius: 12px; margin-top: 50px; font-family: 'Segoe UI', system-ui, sans-serif; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
        <h3 style="color: #102a43; font-size: 24px; margin-top: 0; font-weight: 800; letter-spacing: -0.5px;">Discover the Future with bsdc news</h3>
        <p style="color: #334e68; font-size: 16px; line-height: 1.8; margin-bottom: 15px;">
            At <strong>bsdc news</strong>, we engineer real-time intelligence for the digital frontier. Whether you are scaling full-stack applications, optimizing Knowledge Graph SEO, or deploying cutting-edge infrastructure, our automated aggregation engine ensures you never miss a breakthrough.
        </p>
        <p style="color: #334e68; font-size: 16px; line-height: 1.8; margin-bottom: 0;">
            <em>Empowering developers, students, and tech leaders worldwide with unparalleled industry analysis, 24 hours a day, 7 days a week.</em>
        </p>
    </div>
    """

    return f"""
    <script type="application/ld+json">{json.dumps(schema)}</script>
    <div style="font-family: system-ui, -apple-system, sans-serif;">
        <span style="background-color:#e2e8f0; color:#475569; padding:4px 10px; border-radius:20px; font-size:13px; font-weight:600;">⏱️ {read_time}</span>
        <div style="margin: 25px 0;"><img src="{main_image}" style="width:100%; border-radius:12px; box-shadow: 0 5px 15px rgba(0,0,0,0.15);" alt="{title}"></div>
        <div style="font-size: 18px; line-height: 1.85; color: #1a202c;">
            {body_html}
        </div>
        <hr style="border:0; border-top:1px solid #cbd5e1; margin: 40px 0;">
        <p style="font-size: 14px; color: #64748b;">
            <em>Source validation by <strong>{source_name}</strong>. Explore the original technical report <a href="{source_url}" target="_blank" rel="nofollow" style="color:#2563eb; text-decoration:none; font-weight:600;">here</a>.</em>
        </p>
        {bsdc_seo_footer}
    </div>
    """

# ---------------------------------------------------------
# INDEXING & PUBLISHING
# ---------------------------------------------------------
def submit_to_search_engines(urls):
    """Fires Google Indexing API and IndexNow concurrently."""
    if not urls: return
    print(Fore.CYAN + f"\n⚡ Launching automated indexing for {len(urls)} URLs...")
    
    # 1. Google
    google_service = get_indexing_service()
    if google_service:
        for url in urls:
            try:
                google_service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
                print(Fore.GREEN + f"   [Google] Indexed: {url}")
            except Exception as e:
                print(Fore.RED + f"   [Google] Failed: {e}")
                
    # 2. Bing/IndexNow
    try:
        domain = urls[0].split('/')[2]
        payload = {"host": domain, "key": "bsdcnewsindexnowkey123", "keyLocation": f"https://{domain}/bsdcnewsindexnowkey123.txt", "urlList": urls}
        res = requests.post("https://api.indexnow.org/indexnow", json=payload, timeout=10)
        if res.status_code in [200, 202]:
            print(Fore.GREEN + f"   [IndexNow] Successfully pushed batch to Bing/Yandex.")
    except Exception as e:
        print(Fore.RED + f"   [IndexNow] Failed: {e}")

def main():
    print(Fore.MAGENTA + Style.BRIGHT + "========================================")
    print(Fore.MAGENTA + Style.BRIGHT + "🚀 bsdc news V3 - Enterprise Automation")
    print(Fore.MAGENTA + Style.BRIGHT + "========================================")
    
    blogger = get_blogger_service()
    
    # Get existing history
    posts_req = blogger.posts().list(blogId=BLOG_ID, maxResults=50).execute()
    existing_items = posts_req.get('items', [])
    existing_titles = {p.get('title', '') for p in existing_items}
    existing_urls = [p.get('url') for p in existing_items if p.get('url')]
    
    print(Fore.YELLOW + "📡 Connecting to global RSS streams...")
    
    # Concurrent Processing for maximum speed
    candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for feed_url in RSS_FEEDS:
            try:
                parsed = feedparser.parse(feed_url)
                source_name = parsed.feed.get('title', 'Tech News')
                for entry in parsed.entries[:10]: # Check top 10 per feed
                    futures.append(executor.submit(process_single_article, entry, source_name, existing_titles))
            except: continue
            
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                candidates.append(result)
                if len(candidates) >= 5: # Enforce min 5 articles target
                    break

    if len(candidates) < 5:
        print(Fore.YELLOW + f"⚠️ Only found {len(candidates)} qualifying articles (Need 5+). Waiting for next cycle to maintain quality.")
        return

    print(Fore.GREEN + f"✅ Validated {len(candidates)} high-SEO articles. Commencing publishing matrix...")
    
    published_urls = []
    for idx, article in enumerate(candidates[:8], 1): # Post up to 8 max per run
        print(Fore.CYAN + f"📝 ({idx}) Publishing: {article['title'][:60]}...")
        try:
            res = blogger.posts().insert(blogId=BLOG_ID, body={"title": article["title"], "content": article["content"], "labels": article["labels"]}).execute()
            post_url = res.get('url')
            if post_url:
                published_urls.append(post_url)
            time.sleep(2)
        except Exception as e:
            print(Fore.RED + f"   ❌ Failed: {e}")

    # Trigger SEO Indexing
    target_indexing_urls = list(set(published_urls + existing_urls[:20])) # Backfill old articles
    submit_to_search_engines(target_indexing_urls)
    
    print(Fore.MAGENTA + Style.BRIGHT + "========================================")
    print(Fore.MAGENTA + Style.BRIGHT + "🏆 Sequence Complete. See you in 15 mins.")
    print(Fore.MAGENTA + Style.BRIGHT + "========================================")

if __name__ == "__main__":
    main()
