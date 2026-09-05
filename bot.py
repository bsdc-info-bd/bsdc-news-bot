import os
import sys
import time
import feedparser
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()

if not all([BLOG_ID, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    print("❌ ERROR: Missing required GitHub Secrets.")
    sys.exit(1)

RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://www.engadget.com/rss.xml",
    "https://www.zdnet.com/news/rss.xml"
]

def get_blogger_service():
    creds = Credentials(
        None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("blogger", "v3", credentials=creds)

def extract_image_url(entry):
    """Hunts for images across all possible RSS and HTML data structures."""
    # 1. Check standard media tags
    if 'media_content' in entry and entry.media_content:
        return entry.media_content[0].get('url')
    if 'media_thumbnail' in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    if 'enclosures' in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    
    # 2. Check HTML content/summary using BeautifulSoup
    html_content = getattr(entry, 'summary', '')
    if hasattr(entry, 'content') and entry.content:
        html_content += entry.content[0].value
        
    if html_content:
        soup = BeautifulSoup(html_content, 'html.parser')
        img_tag = soup.find('img')
        if img_tag and img_tag.get('src'):
            return img_tag['src']
            
    return None

def clean_summary_text(html_content):
    """Removes all HTML tags to get a clean text summary."""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator=' ').strip()
    # Limit to ~400 characters to keep it a snippet
    return text[:400] + "..." if len(text) > 400 else text

def get_existing_posts(service):
    posts = service.posts().list(blogId=BLOG_ID, maxResults=50).execute()
    return {item.get('title', '') for item in posts.get('items', [])}

def fetch_articles(existing_titles, max_posts=5):
    articles = []
    
    for feed_url in RSS_FEEDS:
        if len(articles) >= max_posts:
            break
            
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get('title', 'Tech News')
            
            for entry in feed.entries:
                if len(articles) >= max_posts:
                    break
                    
                if entry.title not in existing_titles:
                    image_url = extract_image_url(entry)
                    
                    # STRICT RULE: Skip if no image is found
                    if not image_url:
                        continue
                        
                    raw_summary = getattr(entry, 'summary', '')
                    clean_text = clean_summary_text(raw_summary)

                    image_html = f'<div style="text-align: center; margin-bottom: 20px;"><img src="{image_url}" style="max-width: 100%; height: auto; border-radius: 8px;" alt="{entry.title}"></div>'

                    formatted_content = f"""
                    {image_html}
                    <div style="font-size: 16px; line-height: 1.6; color: #222;">
                        <p>{clean_text}</p>
                    </div>
                    <hr style="border: 0; border-top: 1px solid #eaeaea; margin: 25px 0;">
                    <p style="font-size: 14px; color: #666;">
                        <em>Source: <strong>{source_name}</strong> | <a href="{entry.link}" target="_blank" rel="nofollow">Read full article</a></em>
                    </p>
                    """
                    
                    articles.append({
                        "title": entry.title,
                        "content": formatted_content,
                        "labels": ["Tech News", "Technology"]
                    })
                    
                    # Add to existing titles temporarily so we don't duplicate within the same run
                    existing_titles.add(entry.title)
                    
        except Exception as e:
            print(f"⚠️ Feed error ({feed_url}): {e}")
            continue
            
    return articles

def main():
    print("🚀 Fetching top-tier tech news (Target: 3-5 posts with images)...")
    service = get_blogger_service()
    existing_titles = get_existing_posts(service)
    
    articles_to_publish = fetch_articles(existing_titles, max_posts=5)
    
    if not articles_to_publish:
        print("💤 No new unique articles with images found right now.")
        return

    print(f"✅ Found {len(articles_to_publish)} suitable articles. Publishing now...")
    
    for idx, article in enumerate(articles_to_publish, 1):
        print(f"📝 ({idx}/{len(articles_to_publish)}) Publishing: '{article['title']}'...")
        body = {
            "title": article["title"],
            "content": article["content"],
            "labels": article["labels"]
        }
        try:
            response = service.posts().insert(blogId=BLOG_ID, body=body).execute()
            print(f"   🎉 Success! (Post ID: {response['id']})")
            time.sleep(2) # Pause briefly to prevent Google API rate limiting
        except HttpError as e:
            print(f"   ❌ Failed to publish this post. Details: {e}")

if __name__ == "__main__":
    main()
