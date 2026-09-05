import os
import sys
import re
import feedparser
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

# High-Authority Tech News Feeds Only
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
    """Extracts the highest quality image available from RSS metadata or HTML tags."""
    if 'media_content' in entry and entry.media_content:
        return entry.media_content[0].get('url')
    if 'media_thumbnail' in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    if 'enclosures' in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    
    # Fallback to searching summary/content for <img> tag
    content_str = getattr(entry, 'summary', '')
    if hasattr(entry, 'content') and entry.content:
        content_str += entry.content[0].value
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_str)
    if match:
        return match.group(1)
    return None

def clean_summary(summary_html):
    """Removes inline image tags from the feed summary to avoid duplicates."""
    cleaned = re.sub(r'<img[^>]*>', '', summary_html)
    return cleaned.strip()

def get_existing_posts(service):
    posts = service.posts().list(blogId=BLOG_ID, maxResults=50).execute()
    return {item.get('title', '') for item in posts.get('items', [])}

def fetch_latest_news(existing_titles):
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                if entry.title not in existing_titles:
                    image_url = extract_image_url(entry)
                    raw_summary = getattr(entry, 'summary', 'No summary available.')
                    summary = clean_summary(raw_summary)
                    source_name = feed.feed.get('title', 'Tech News')

                    image_html = f'<div style="text-align: center; margin-bottom: 20px;"><img src="{image_url}" style="max-width: 100%; height: auto; border-radius: 8px;" alt="{entry.title}"></div>' if image_url else ''

                    formatted_content = f"""
                    {image_html}
                    <div style="font-size: 16px; line-height: 1.6; color: #222;">
                        {summary}
                    </div>
                    <hr style="border: 0; border-top: 1px solid #eaeaea; margin: 25px 0;">
                    <p style="font-size: 14px; color: #666;">
                        <em>Source: <strong>{source_name}</strong> | <a href="{entry.link}" target="_blank" rel="nofollow">Read original article</a></em>
                    </p>
                    """
                    return {
                        "title": entry.title,
                        "content": formatted_content,
                        "labels": ["Tech News", "Technology", "Latest News"]
                    }
        except Exception as e:
            print(f"⚠️ Feed error ({feed_url}): {e}")
            continue
    return None

def main():
    print("🚀 Fetching top-tier tech news...")
    service = get_blogger_service()
    existing_titles = get_existing_posts(service)
    
    article = fetch_latest_news(existing_titles)
    if article:
        print(f"📝 Publishing: '{article['title']}'...")
        body = {
            "title": article["title"],
            "content": article["content"],
            "labels": article["labels"]
        }
        response = service.posts().insert(blogId=BLOG_ID, body=body).execute()
        print(f"🎉 Successfully published! (Post ID: {response['id']})")
    else:
        print("💤 No new unique articles found right now.")

if __name__ == "__main__":
    main()
