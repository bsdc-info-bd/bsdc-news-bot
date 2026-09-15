import os
import sys
from colorama import init, Fore

init(autoreset=True)

def sanitize_secret(key):
    val = os.environ.get(key, "").strip()
    # Strip stray brackets or quotes pasted by accident
    return val.strip("[]\"' ")

BLOG_ID = sanitize_secret("BLOG_ID")
CLIENT_ID = sanitize_secret("GOOGLE_CLIENT_ID")
CLIENT_SECRET = sanitize_secret("GOOGLE_CLIENT_SECRET")
REFRESH_TOKEN = sanitize_secret("GOOGLE_REFRESH_TOKEN")
INDEXING_JSON = sanitize_secret("INDEXING_SERVICE_ACCOUNT_JSON")
GEMINI_KEY = sanitize_secret("GEMINI_API_KEY")

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
