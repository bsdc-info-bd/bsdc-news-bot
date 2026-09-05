import os
import sys
import feedparser
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 1. Pull Secrets (with error checking)
BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()

if not all([BLOG_ID, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    print("❌ ERROR: Missing one or more GitHub Secrets. Please check your repository settings.")
    sys.exit(1)

# Reliable tech/code RSS feeds
RSS_FEEDS = [
    "https://dev.to/feed",
    "https://news.ycombinator.com/rss",
    "https://github.blog/feed/"
]

def get_blogger_service():
    try:
        creds = Credentials(
            None,
            refresh_token=REFRESH_TOKEN,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("blogger", "v3", credentials=creds)
    except Exception as e:
        print(f"❌ AUTH ERROR: Failed to authenticate with Google. Check your Refresh Token. Details: {e}")
        sys.exit(1)

def get_existing_posts(service):
    try:
        posts = service.posts().list(blogId=BLOG_ID, maxResults=50).execute()
        return {item.get('title', '') for item in posts.get('items', [])}
    except HttpError as e:
        print(f"❌ API ERROR: Failed to fetch blog posts. Make sure your BLOG_ID ({BLOG_ID}) is correct. Details: {e}")
        sys.exit(1)

def fetch_latest_article(existing_titles):
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                if entry.title not in existing_titles:
                    summary = getattr(entry, 'summary', 'No summary available.')
                    content = f"""
                    <p>{summary}</p>
                    <br>
                    <p><em>Originally published at: <a href="{entry.link}" target="_blank" rel="nofollow">{entry.link}</a></em></p>
                    """
                    return {
                        "title": entry.title,
                        "content": content
                    }
        except Exception as e:
            print(f"⚠️ Warning: Failed to parse feed {feed_url}. Details: {e}")
            continue
    return None

def main():
    print("🚀 Starting bsdc news bot...")
    service = get_blogger_service()
    
    print("✅ Authenticated with Google successfully.")
    existing_titles = get_existing_posts(service)
    
    print(f"🔍 Found {len(existing_titles)} recent posts on your blog.")
    article = fetch_latest_article(existing_titles)
    
    if article:
        print(f"📝 Attempting to publish: '{article['title']}'...")
        body = {
            "title": article["title"],
            "content": article["content"]
        }
        try:
            response = service.posts().insert(blogId=BLOG_ID, body=body).execute()
            print(f"🎉 Successfully published! (Post ID: {response['id']})")
        except HttpError as e:
            print(f"❌ PUBLISH ERROR: Failed to insert post. Details: {e}")
            sys.exit(1)
    else:
        print("💤 No new unique articles found to publish right now.")

if __name__ == "__main__":
    main()
