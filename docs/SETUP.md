# Setup guide (100% free)

Everything below uses free services: GitHub Actions, Blogger, Google Cloud's free APIs, and the free tiers of the AI providers.

## 1. Required secrets (same names as v5)

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Where to get it |
|---|---|
| `BLOG_ID` | Blogger dashboard URL → the number after `blogID=` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google Cloud Console → APIs & Services → Credentials → **Create OAuth client** (type *Desktop app*). Enable **Blogger API v3** first. |
| `GOOGLE_REFRESH_TOKEN` | Run `python scripts/get_refresh_token.py --client-id … --client-secret …` on your computer. Set the OAuth consent screen to **In production**, or the token expires after 7 days. |

## 2. AI writer (optional but recommended — pick one or more)

| Secret | Free tier | Get a key |
|---|---|---|
| `GEMINI_API_KEY` | Free tier on the Gemini Flash models | https://aistudio.google.com/api-keys (new keys start with `AQ.`) |
| `GROQ_API_KEY` | ~1,000 requests/day per model | https://console.groq.com/keys |
| `OPENROUTER_API_KEY` | Free `openrouter/free` router | https://openrouter.ai/settings/keys |
| `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | Workers AI daily free allocation | https://dash.cloudflare.com → AI → Workers AI |
| `HF_TOKEN` | Free monthly inference credits | https://huggingface.co/settings/tokens |

The bot tries the providers in the order set in `config/settings.yaml` (`ai.providers`) and skips any without a key.

**No AI key at all?** The site still publishes. It uses short, clearly attributed news briefs (extractive summaries that link to the original article) and labels them "News Brief".

## 3. Indexing (optional)

* `INDEXING_SERVICE_ACCOUNT_JSON`: the whole JSON key of a Google Cloud service account.
  1. Enable the **Web Search Indexing API**.
  2. Add the service-account e-mail as an **Owner** in Search Console.
  3. The bot tracks the 200 URLs/day quota and queues any overflow for the next day.
* `INDEXNOW_KEY`: only when you use a custom domain (see `docs/SEO.md`).
* Blog feed pings to WebSub hubs are automatic and need no key.

## 4. Notifications & auto-sharing (optional)

| Feature | Secrets |
|---|---|
| Telegram alerts + run summaries | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (create a bot with @BotFather) |
| Auto-post to a Telegram channel | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` (e.g. `@bsdcnews`; make the bot an admin) |
| Discord / Slack alerts | `DISCORD_WEBHOOK_URL` / `SLACK_WEBHOOK_URL` |
| Facebook Page | `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN` (long-lived page token) |
| Mastodon | `MASTODON_BASE_URL` (e.g. `https://mastodon.social`), `MASTODON_ACCESS_TOKEN` |
| Bluesky | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` (Settings → App passwords) |

## 5. Optional repository variable

**Settings → Secrets and variables → Actions → Variables → `SITE_URL`**, e.g. `https://bsdcnews.blogspot.com`. You can leave it empty, because the bot reads the URL from Blogger.

## 6. Upgrade the GitHub Actions workflow (recommended, 1 minute)

The bot code in this repository is v6, but automated tools are not allowed to modify
files under `.github/workflows/` unless the repository grants the `workflows`
permission — so the improved workflow ships as a ready-to-paste file instead:

* `docs/workflows/auto_poster.yml` — the v6 publisher workflow
* `docs/workflows/tests.yml` — lint + test + dry-run smoke test on every push

To install it (needs your own GitHub login, which always has the right permission):

1. On GitHub, open **`.github/workflows/auto_poster.yml`** → pencil icon (**Edit**).
2. Select all, delete, then paste the whole contents of **`docs/workflows/auto_poster.yml`**.
3. Commit to `main`. (Optional: create `.github/workflows/tests.yml` the same way from `docs/workflows/tests.yml`.)

What the v6 workflow adds over the v5 one:

| Feature | v5 (current) | v6 (`docs/workflows/`) |
| --- | --- | --- |
| Schedule | `*/15 * * * *` (GitHub throttles/skips these) | `7,22,37,52 * * * *` (reliable) |
| Manual runs | no options | `task` = doctor / run / feeds / preview, `dry_run`, `max_posts`, `mode` |
| Overlapping runs | can double-publish | `concurrency` group cancels duplicates |
| Memory between runs | none (re-reads the blog every time) | `data/state.json` persisted to the `bot-data` branch |
| Disabled after 60 days | silently stops | keepalive step re-enables the workflow |
| Actions versions | checkout@v4, setup-python@v5 | current, Node-24 actions |
| Failure reporting | always green | real exit codes + run summary + artifact |

**Everything still works without this step** — the v5 workflow calls `python main.py`,
which is now the v6 engine with the same secret names. You only lose the features in the
table above (notably: no `doctor`/`dry_run` buttons and no state carried between runs).

## 7. Test it

1. **Actions → the publisher workflow → Run workflow** and pick the branch. With the v6
   workflow: task = `doctor` → fix anything marked ❌, then **dry_run = true**, then a normal run.
   With the v5 workflow there are no options, so a dispatch is a real publishing run —
   start with `max_posts_per_run: 1` in `config/settings.yaml`.
2. Read the run log: each article shows `published`, `skipped` or `failed` with the reason.
3. From then on the schedule runs automatically.

## 8. Customise without code

* `config/feeds.yaml`: add or remove sources, weights and categories.
* `config/settings.yaml`: posts per run/day, quiet hours, draft mode, quality threshold, AI models, labels, image options, indexing, alert thresholds.
* `prompts/article.md`: the editorial prompt the AI receives.

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # fill in what you have
python main.py doctor
python main.py run --dry-run    # never publishes
python -m bsdc_news preview https://www.theverge.com/some-article   # renders preview.html
pytest -q && ruff check .
```
