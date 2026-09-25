# 📰 bsdc news — Smart Publisher v6

A fully automated, smart news publishing system for the **bsdc news** Blogger site. It runs on **100% free** infrastructure: GitHub Actions, the Blogger API, Google's free APIs — and its own built-in writing engine, so **no AI provider, no API key and no per-article cost**.

Every ~15 minutes it:

1. reads 15 tech news feeds;
2. picks the most important *new* stories, using trends, multi-source coverage and freshness;
3. extracts the article text and images;
4. writes an original, SEO-structured article with the local **BSDC Cortex** engine (fact extraction, entity recognition, headline generation, readability control, paraphrasing, FAQ and TL;DR — all in pure Python);
5. checks quality and facts;
6. publishes to Blogger with schema.org markup;
7. notifies search engines, shares to social networks, and reports everything.

> **Upgrading from v5?** Nothing to change: `python main.py` and all secret names are the same. See [What was broken in v5](#what-was-broken-in-v5-and-is-fixed-now).

---

## What changed in v7 (no AI, all local)

* Every external language-model provider was removed: no Gemini, Groq, OpenRouter, Cloudflare or HuggingFace calls, no keys, no quotas, no `401`s, no cost.
* Articles are written by `bsdc_news/cortex/` — 60+ modules of pure-Python text analysis and composition.
* SEO is planned once per article by `bsdc_news/seo/` (title tag, meta description, slug, heading hierarchy, keyword density, internal links, breadcrumbs, OG/Twitter cards, sitemap and robots entries, JSON-LD graph) and scored by a 40-check on-page audit.
* The published post is re-stamped with its real Blogger URL, so canonical, `og:url` and schema URLs are never wrong.
* Indexing stays multi-channel and free: Google Indexing API, IndexNow (when the key file is reachable), Bing and WebSub hub pings — each degrading to a logged skip instead of failing the run.

## Quick start

1. Keep your existing secrets (`BLOG_ID`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`). `INDEXING_SERVICE_ACCOUNT_JSON` stays optional (free, unlocks the Google Indexing API).
2. **Delete `GEMINI_API_KEY` / `GROQ_API_KEY` if you like** — v7 writes locally and ignores them. Nothing in the pipeline calls a language model any more, so the `401 ACCESS_TOKEN_TYPE_UNSUPPORTED` failure class is gone for good.
3. **Install the v6 workflow** (one paste, only you can do it — bots need the `workflows` permission): open [`.github/workflows/auto_poster.yml`](.github/workflows/auto_poster.yml) on GitHub, click the pencil, replace its contents with [`docs/workflows/auto_poster.yml`](docs/workflows/auto_poster.yml) and commit. Without this step the old workflow still runs the new engine, but you lose the `doctor` / `dry_run` buttons, state between runs and the fixed schedule — see [docs/SETUP.md §6](docs/SETUP.md).
4. **Actions → bsdc news 6.0 Smart Publisher → Run workflow → task `doctor`**. This checks everything and explains any fix.
5. Run once with **dry_run = true**, then let the schedule take over.

Full guide: [docs/SETUP.md](docs/SETUP.md) · Problems: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) · SEO: [docs/SEO.md](docs/SEO.md)

---

## What was broken in v5 (and is fixed now)

Found in the real GitHub Actions logs. Every scheduled run showed ✅ "success" while **publishing zero posts**.

| # | Error | Fix |
|---|---|---|
| 1 | Every AI call: `401 UNAUTHENTICATED – ACCESS_TOKEN_TYPE_UNSUPPORTED`. With `if not ai_html: continue`, nothing was published. | Several causes: `gemini-2.5-flash` hard-coded; `google-auth==2.27.0` forcing an ancient `google-genai 1.55`; and Google's 2026 switch to new `AQ.` API keys. v6 uses REST with a chain of current models, detects a rejected key with a clear fix message, fails over to other free providers, and still publishes attributed news briefs if every AI is down. |
| 2 | Google Indexing API: `No access token in response` for every URL | The OAuth scope was a Markdown link (`[https://…](https://…)`) instead of a URL. |
| 3 | IndexNow: `No connection adapters were found for '[https://api.indexnow.org/indexnow](…)'` | Same corrupted-link problem. IndexNow now also verifies the key file first. |
| 4 | NewsArticle schema `@context` was a Markdown link, so Google ignored it | Fixed, and a test blocks this class of bug forever. |
| 5 | Workflow always green | Real exit codes, a job summary, and alerts after repeated failures. |
| 6 | Re-submitted the same 15 old URLs to the Indexing API every run (wasted the 200/day quota) | Only new posts are submitted, with quota tracking and a queue. |
| 7 | Dedupe only by exact title among the last 50 posts | Persistent state + canonical URLs + fuzzy title matching + state rebuild from the blog. |
| 8 | Images: any `<img>` on the page (ads, avatars, logos), relative URLs dropped | Ranked og:image/JSON-LD/article images, real dimension checks, junk filters. |
| 9 | Titles not HTML-escaped (broken markup, XSS risk) | Everything is escaped and sanitised. |
| 10 | `config.py` called `sys.exit(1)` on import; genai client created on import; `datetime.utcnow` deprecated | Fixed. |
| 11 | Cron `*/15` fired only ~7×/day; Node 20 actions deprecated | Odd-minute schedule, `checkout@v7` / `setup-python@v6`, concurrency lock, schedule keep-alive. |
| 12 | Deals/coupon spam ("T-Mobile Promo Codes: 25% Off") selected as news | Editorial filters. |

---

## ✨ Features (120)

### Sourcing & smart selection
1. 15 curated feeds in `config/feeds.yaml`: the 6 originals + BleepingComputer, MIT Tech Review, 9to5Google, 9to5Mac, Android Authority, The Register, Tom's Hardware, Electrek, The Daily Star (Bangladesh).
2. Add, remove or disable feeds without code.
3. Per-feed weight, category, language and item limit.
4. Parallel feed fetching.
5. Per-feed error isolation: one broken feed never stops a run.
6. RSS and Atom support, including FeedBurner original links.
7. Feed images from `media:content`, `media:thumbnail`, enclosures and inline `<img>`.
8. Canonical URL normalisation (tracking parameters, `www`, AMP and fragments removed).
9. Freshness scoring with exponential decay (configurable half-life).
10. "Hotness" boost when several outlets cover the same story.
11. Free Google Trends RSS boost for trending topics (US + Bangladesh by default).
12. Priority-keyword boost (AI, Apple, Google, Bangladesh …).
13. Story clustering: the best source is picked as the representative.
14. Diversity caps per source and per category in every run.
15. Maximum article age filter.
16. Blocked keywords (coupons, promo codes, betting, NSFW …).
17. Low-value headline detection (deals, listicles, puzzles, podcasts, webinars, sponsored).
18. Blocked URL patterns (`/deals/`, `/video/`, `/live/` …) and blocked domains.
19. English-language check on headlines.
20. Minimum headline length.

### De-duplication & memory
21. Persistent state file (`state.json` on the `bot-data` branch).
22. Never re-publishes a URL, even with different tracking parameters.
23. Order-independent headline fingerprints.
24. Fuzzy near-duplicate detection against recent blog posts.
25. Reads the last 150 live **and scheduled** blog posts before publishing.
26. State auto-rebuilds from the blog's source links if the state is lost.
27. Failed-article back-off with a retry window and maximum attempts.
28. Permanent failures (404, paywall, robots) are never retried.
29. Crash-safe: state is saved after every post, with atomic writes.
30. Corrupt state files are detected and backed up automatically.
31. Retention pruning keeps the state small.

### Extraction
32. trafilatura main-text extraction (precision mode).
33. JSON-LD `articleBody` fallback.
34. Paragraph fallback for unusual layouts.
35. Boilerplate line cleaner (ads, "read more", credits, newsletter prompts).
36. Metadata: author, published/modified dates, site name, description, keywords, language, canonical.
37. Paywall detection.
38. robots.txt respected.
39. Polite per-host rate limiting.
40. Retries with exponential back-off and `Retry-After` support.
41. Cloudflare challenge fallback via cloudscraper.
42. 6 MB page size cap and correct character-set decoding.

### Images
43. og:image / Twitter / JSON-LD / article-figure image discovery.
44. Lazy-load attributes (`data-src`, `data-lazy-src` …) and largest `srcset` candidate.
45. Relative → absolute URL resolution.
46. Token-based junk filter (logos, avatars, icons, ads, tracking pixels, SVG/GIF).
47. Image ranking by origin, size, aspect ratio, caption and alt text.
48. Real dimension check by downloading only the first 64 KB (pure-Python PNG/JPEG/GIF/WebP/AVIF parser).
49. Minimum width and aspect-ratio limits.
50. Captions and credits preserved from the source.
51. Free CC-licensed fallback images from **Openverse**, with creator and licence links.
52. Free **wsrv.nl** image CDN: resized, WebP, cached; no hot-linking.
53. `width`/`height` on images (no layout shift) and lazy loading below the fold.

### Writing engine (BSDC Cortex — local, free, keyless)
54. **Fact extraction** — numbers, dates, quotes and claims are pulled from the source and scored, so every sentence is traceable to evidence.
55. **Entity recognition** with a bundled gazetteer (people, companies, places, Bangladesh institutions) driving tags, schema and internal links.
56. **Headline generation** with candidate ranking, length control, sentence case and a clickbait guard.
57. **Outline planning** — sections are decided before they are written, with a word budget each.
58. **Lede and standfirst composition** in house style, never opening on a quotation.
59. **Paraphrase and simplification** to a target US grade level (default 12) with a coherence check.
60. **TL;DR, key points and FAQ blocks** generated from the source and emitted as FAQPage schema.
61. **Keyword extraction** (TF-IDF + RAKE + TextRank) with headline anchoring, entity truncation, verb-fragment rejection and stuffing protection.
62. **Quality gate with revision passes** — length, readability, originality, structure and grounding are scored; a draft is revised or rejected rather than padded.
63. **Novelty check** against published titles and bodies, so one story is never written twice.
64. **Multilingual** — English by default, Bangla sources supported (`BSDC_WRITER_LANGUAGES=en,bn`), with Bangla-to-ASCII slug transliteration.

### Quality & safety
72. Quality score 0–100 with a configurable threshold.
73. Length, structure (H2 count, paragraphs, lists) and long-paragraph checks.
74. Plagiarism guard: 8-gram verbatim-overlap check against the source.
75. Hallucination guard: numbers that are not in the source are flagged.
76. Prompt-leak and "as an AI" detection.
77. Markdown leftover detection and conversion.
78. Whitelist HTML sanitiser (scripts, iframes, event handlers and `javascript:` URLs removed).
79. HTML escaping everywhere (titles, alt text, captions, JSON-LD).
80. Script-safe JSON-LD encoding.
81. Clean-headline rules (outlet suffixes, "BREAKING:", ALL-CAPS, length).
82. Near-duplicate AI headline protection.
83. **Non-AI fallback writer**: extractive, attributed news briefs keep the site publishing during AI outages.
84. `ai_failure_mode`: brief / draft (for manual review) / skip.
85. "News Brief" label on non-AI posts.

### Post design & SEO
86. Summary first (Blogger snippet + meta description) and hero image.
87. `<!--more-->` jump break for homepage cards.
88. Category pill, reading time and source line.
89. Key Takeaways box.
90. Inline second image after the first section.
91. FAQ section.
92. `NewsArticle` JSON-LD with self-referencing URL (post patched after insert).
93. `FAQPage` and `BreadcrumbList` JSON-LD.
94. `isBasedOn`, `wordCount`, `articleSection`, `keywords`, publisher logo support.
95. Automatic category classification (11 categories, including Bangladesh; extendable in YAML).
96. Smart labels: category + main entities + AI tags, capped.
97. Source attribution with a nofollow link and "also covered by" outlets.
98. AI-assistance disclosure on AI-written posts.
99. Share buttons (Facebook, X, WhatsApp, Telegram, LinkedIn, Reddit).
100. Internal links to recent posts.
101. "About bsdc news" footer (kept from v5).

### Publishing control
102. Posts per run and per day limits.
103. Even pacing across the day in the site's timezone.
104. Quiet hours with a reduced night-time budget.
105. Live or draft publishing mode.
106. Staggered scheduling through Blogger (`stagger_minutes`).
107. Typed Blogger errors with exact fixes (expired token, wrong blog, no permission).

### Indexing & distribution
108. Google Indexing API with the fixed scope, 200/day quota tracking and an overflow queue.
109. IndexNow with the fixed endpoint and key-file verification.
110. Bing URL Submission API (optional free key).
111. WebSub/PubSubHubbub pings for the blog feed.
112. Auto-post to a Telegram channel (with image), Facebook Page, Mastodon and Bluesky, each isolated from failures.

### Operations & monitoring
113. **`doctor` command**: live check of Blogger, every AI provider, indexing, feeds and integrations.
114. Real exit codes: red runs when publishing is broken; no more fake "success".
115. GitHub job summary: table of posts, writers, quality scores, warnings and filter statistics.
116. Telegram / Discord / Slack alerts with anti-spam thresholds; publish summaries.
117. JSON run history and a static HTML **dashboard** (`bot-data` branch, GitHub Pages ready).
118. Secret masking in logs, reports and state; GitHub annotations and collapsible log groups.
119. Dry-run mode (reads the real blog, never writes), plus `feeds`, `preview` and `dashboard` commands.
120. Workflow: odd-minute cron, concurrency lock, manual inputs (task, dry run, max posts, mode), state branch, schedule keep-alive, Node-24 actions, CI tests + lint, and 88 offline tests.

---

## Architecture

```
main.py                     entry point (unchanged command)
bsdc_news/
  cli.py        doctor.py   commands: run · doctor · feeds · preview · dashboard
  pipeline.py               orchestrator + exit codes
  settings.py   state.py    YAML + env config · persistent memory
  feeds.py  filters.py  dedupe.py  trends.py  ranking.py
  extractor.py  images.py   http.py
  ai/  base.py gemini.py openai_compat.py router.py
  brief.py                  non-AI fallback writer
  content/ sanitize.py quality.py taxonomy.py seo.py render.py
  blogger.py  indexing.py  social.py  notify.py  report.py  log.py  errors.py  utils.py
config/  settings.yaml feeds.yaml       prompts/article.md
scripts/ get_refresh_token.py indexnow_key.py
tests/   88 offline tests (fixtures, fakes for HTTP/Blogger/AI)
```

The old modules (`config.py`, `scraper.py`, `ai_rewriter.py`, `image_handler.py`, `blogger_publisher.py`, `indexing_engine.py`) remain as thin, fixed compatibility wrappers.

## Commands

```bash
python main.py                         # scheduled run
python main.py run --dry-run           # everything except publishing
python main.py run --draft --max-posts 2
python main.py run --no-ai             # brief writer only
python main.py doctor                  # diagnose secrets & APIs
python main.py feeds                   # test all feeds
python -m bsdc_news preview <url>      # render one article to preview.html
python main.py dashboard               # rebuild the status page
```

## Free stack

| Need | Service | Cost |
|---|---|---|
| Scheduler & runner | GitHub Actions | free |
| Hosting | Blogger | free |
| AI writing | Gemini, Groq, OpenRouter, Cloudflare Workers AI, Hugging Face (free tiers) | free |
| Images | Source images, Openverse (CC licences), wsrv.nl CDN | free |
| Trends | Google Trends RSS | free |
| Indexing | Google Indexing API, IndexNow, Bing API, WebSub | free |
| Alerts & social | Telegram, Discord, Slack, Facebook, Mastodon, Bluesky | free |
| Dashboard | GitHub Pages (optional) | free |

## License

MIT
