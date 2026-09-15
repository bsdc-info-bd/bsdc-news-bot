import os
import sys
from colorama import init, Fore

init(autoreset=True)

BLOG_ID = os.environ.get("BLOG_ID", "").strip()
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
INDEXING_JSON = os.environ.get("INDEXING_SERVICE_ACCOUNT_JSON", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if not all([BLOG_ID, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, GEMINI_KEY]):
    print(Fore.RED + "❌ ERROR: Missing required GitHub Secrets.")
    sys.exit(1)

RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://www.engadget.com/rss.xml",
    "https://www.zdnet.com/news/rss.xml"
]
