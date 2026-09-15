import cloudscraper
import trafilatura
from bs4 import BeautifulSoup

def scrape_article_data(entry_url):
    scraper = cloudscraper.create_scraper()
    try:
        res = scraper.get(entry_url, timeout=12)
        if res.status_code != 200: return None, []
        
        soup = BeautifulSoup(res.text, 'html.parser')
        image_urls = []
        
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('srcset')
            if src and src.startswith('http'):
                clean_src = src.split(' ')[0]
                if not any(bad in clean_src.lower() for bad in ['avatar', 'logo', 'icon', 'tracker', 'ad-', '1x1', 'pixel', 'gravatar']):
                    image_urls.append(clean_src)
                    
        image_urls = list(dict.fromkeys(image_urls))
        raw_text = trafilatura.extract(res.text)
        
        return raw_text, image_urls
    except Exception:
        return None, []
