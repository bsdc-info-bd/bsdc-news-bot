import json
import requests
from config import INDEXING_JSON
from google.oauth2 import service_account
from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_exponential
from colorama import Fore

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_indexing_service():
    if not INDEXING_JSON: return None
    info = json.loads(INDEXING_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["[https://www.googleapis.com/auth/indexing](https://www.googleapis.com/auth/indexing)"])
    return build('indexing', 'v3', credentials=creds)

def push_instant_indexing(urls):
    if not urls: return
    print(Fore.CYAN + f"\n⚡ Launching Indexing Engine on {len(urls)} URLs...")
    
    # Google Indexing API
    g_service = get_indexing_service()
    if g_service:
        for url in urls:
            try:
                g_service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
                print(Fore.GREEN + f"   [Google Indexing API] Pushed: {url}")
            except Exception as e:
                print(Fore.RED + f"   [Google Indexing API] Error: {e}")

    # Bing IndexNow API
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
            print(Fore.GREEN + f"   [IndexNow] Submitted {len(urls)} URLs successfully.")
    except Exception as e:
        print(Fore.RED + f"   [IndexNow] Error: {e}")
