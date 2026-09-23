# SEO & indexing notes

## What every post gets automatically

* A clean summary as the first paragraph. Blogger uses it as the snippet on home/label pages and in feeds.
* A hero image, then a `<!--more-->` jump break.
* `NewsArticle` JSON-LD with a self-referencing `url` / `mainEntityOfPage`. The post is patched after insert so the schema contains its real URL.
* `BreadcrumbList` and, when available, `FAQPage` JSON-LD.
* Proper H2/H3 structure, a Key Takeaways box, an FAQ section, reading time and category.
* 3–6 relevant labels (category + entities + AI tags). Blogger turns these into label pages.
* Attribution with a `nofollow` link to the original article, plus an `isBasedOn` schema field.
* Images through the free **wsrv.nl** CDN (resized WebP; faster pages, no hot-linking) with width/height to avoid layout shift. Alt text and captions are escaped.
* Share buttons (Facebook, X, WhatsApp, Telegram, LinkedIn, Reddit) with the real post URL.
* Links to recent posts on your own blog, for internal linking.

## Blogger settings to switch on once (Blogger → Settings)

* **Meta tags → Enable search description**: set a site description.
* **Crawlers and indexing → Enable custom robots.txt** (optional) and submit `https://<blog>/sitemap.xml` in Search Console.
* Use a theme that outputs `og:image` / `twitter:card` from the post's first image. Most modern themes do.

> The Blogger API cannot set a post's "search description". That is why the bot puts the summary first in the post body, which Blogger and most themes use as the description.

## Google Indexing API

Google officially supports it only for job postings and livestreams, but it is widely used to speed up crawling. The bot:

* submits **only new posts**. v5 re-submitted the last 15 posts every run and wasted quota.
* tracks the 200 URLs/day quota (Pacific-time reset) and queues any overflow.

## IndexNow (Bing, Yandex, Seznam, Naver, Yep)

IndexNow needs a key file at the root of your domain: `https://example.com/<key>.txt`.

* **`*.blogspot.com` blogs can't host that file**, so the bot skips IndexNow and says so in the log. v5 always submitted with a key file that could not exist.
* **With a custom domain on Cloudflare (free)**:
  1. Run `python scripts/indexnow_key.py`.
  2. Create a Cloudflare Worker route for `yourdomain.com/<key>.txt` that returns the key.
  3. Add the `INDEXNOW_KEY` secret.
  4. The doctor verifies the file.
* Alternatively, set the `BING_WEBMASTER_API_KEY` secret (free, from Bing Webmaster Tools → API access). The bot will also use Bing's URL Submission API.

## WebSub

After publishing, the bot pings Google's and Superfeedr's public WebSub hubs for your blog feed. Feed readers and aggregators then pick up new posts within seconds. This is free and needs no setup.
