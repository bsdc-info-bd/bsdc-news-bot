import time
import feedparser
from config import BLOG_ID, RSS_FEEDS
from scraper import scrape_article_data
from ai_rewriter import rewrite_with_gemini
from image_handler import format_article_images
from blogger_publisher import get_blogger_service, build_final_html
from indexing_engine import push_instant_indexing
from colorama import Fore, Style

def main():
    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")
    print(Fore.MAGENTA + Style.BRIGHT + "🚀 bsdc news 5.0 Enterprise Engine")
    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")

    blogger = get_blogger_service()
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

                print(Fore.YELLOW + f"🔎 Processing: '{entry.title[:50]}...'")
                raw_text, image_urls = scrape_article_data(entry.link)

                # Strict Guard: Article MUST contain high-quality images and adequate body text
                if not image_urls or not raw_text or len(raw_text.split()) < 200:
                    print(Fore.RED + "   ⚠️ Skipped: Missing verified images or insufficient body text.")
                    continue

                print(Fore.BLUE + "   🤖 Structuring Google News Article via AI...")
                ai_html = rewrite_with_gemini(entry.title, raw_text)
                if not ai_html: continue

                main_img, full_body_html = format_article_images(entry.title, ai_html, image_urls)
                final_content = build_final_html(entry.title, full_body_html, main_img, source_name, entry.link)

                res = blogger.posts().insert(
                    blogId=BLOG_ID,
                    body={
                        "title": entry.title,
                        "content": final_content,
                        "labels": ["Tech News", "Google News", "Technology"]
                    }
                ).execute()

                post_url = res.get('url')
                if post_url:
                    published_urls.append(post_url)
                    existing_titles.add(entry.title)
                    print(Fore.GREEN + f"   🎉 Published: {post_url}")

                time.sleep(2)
        except Exception as e:
            print(Fore.RED + f"⚠️ Feed error ({feed_url}): {e}")

    # Trigger indexing for newly published posts and recent entries
    push_instant_indexing(list(set(published_urls + existing_urls[:15])))

    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")
    print(Fore.MAGENTA + Style.BRIGHT + "🏆 bsdc news 5.0 Pipeline Executed.")
    print(Fore.MAGENTA + Style.BRIGHT + "==========================================")

if __name__ == "__main__":
    main()
