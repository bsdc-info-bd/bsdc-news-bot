import os
import feedparser
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BLOG_ID = os.environ.get("BLOG_ID")
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")

# Reliable tech/code RSS feeds you can pull from
RSS_FEEDS = [
    "https://dev.to/feed",
    "https://news.ycombinator.com/rss",
    "https://github.blog/feed/"
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

def get_existing_posts(service):
    # Fetch recent post titles to prevent duplicate publishing
    posts = service.posts().list(blogId=BLOG_ID, maxResults=50).execute()
    return {item['title'] for item in posts.get('items', [])}

def fetch_latest_article(existing_titles):
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            if entry.title not in existing_titles:
                # Format clean HTML content for Blogger
                summary = getattr(entry, 'summary', '')
                content = f"""
                <p>{summary}</p>
                <br>
                <p><em>Originally published at: <a href="{entry.link}" target="_blank" rel="nofollow">{entry.link}</a></em></p>
                """
                return {
                    "title": entry.title,
                    "content": content
                }
    return None

def main():
    service = get_blogger_service()
    existing_titles = get_existing_posts(service)
    
    article = fetch_latest_article(existing_titles)
    
    if article:
        body = {
            "title": article["title"],
            "content": article["content"]
        }
        response = service.posts().insert(blogId=BLOG_ID, body=body).execute()
        print(f"Successfully published: {article['title']} (Post ID: {response['id']})")
    else:
        print("No new unique articles found to publish.")

if __name__ == "__main__":
    main()
