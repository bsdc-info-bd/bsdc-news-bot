# Troubleshooting

Start with the doctor. It checks every secret and API live and tells you how to fix each problem:

**GitHub → Actions → "bsdc news 6.0 Smart Publisher" → Run workflow → task: `doctor`**

(or `python main.py doctor` locally)

---

## Errors found in the v5 production logs (all fixed in v6)

| What the log said | Cause | Status in v6 |
|---|---|---|
| `AI Generation Error: 401 UNAUTHENTICATED … ACCESS_TOKEN_TYPE_UNSUPPORTED` on **every** article | **Two causes.** (1) The bot was hard-coded to `gemini-2.5-flash` through an old SDK. The old `requirements.txt` pinned `google-auth==2.27.0`, which silently forced pip to install `google-genai 1.55`. (2) Google changed Gemini API keys in 2026: new keys start with `AQ.`, and the old `AIza…` keys are rejected from September 2026. | The code is fixed. v6 calls Gemini over REST, tries several current models in turn, and detects a rejected key. **If the doctor still reports a 401 for every model, you must create a new key** (see below). |
| `[Google Indexing API] Error: ('No access token in response.' …)` | The OAuth scope string had been pasted as a Markdown link (`[https://…](https://…)`) instead of a plain URL. | ✅ Fixed. A regression test fails the build if a Markdown link appears in code again. |
| `[IndexNow] Error: No connection adapters were found for '[https://api.indexnow.org/indexnow](…)'` | Same Markdown-link paste problem in the endpoint. | ✅ Fixed. IndexNow now also checks your key file before submitting. |
| NewsArticle schema `"@context": "[https://schema.org](https://schema.org)"` | Same paste problem, so Google ignored the structured data. | ✅ Fixed. |
| The workflow shows ✅ "success" even though nothing was published | `main.py` swallowed every error and always exited with 0. | ✅ Fixed. A run is ❌ red when it publishes nothing after trying several candidates, when Blogger/OAuth is broken, or when the config is invalid. An AI key rejection turns the run red at most once a day. Posts still go out through the fallback writer. |
| Runs happen every few hours instead of every 15 min | GitHub drops many cron jobs scheduled at `:00/:15/:30/:45` under load. | ✅ The schedule now uses odd minutes (`7,22,37,52`). |
| `Node.js 20 is deprecated … actions/checkout@v4, actions/setup-python@v5` | Outdated actions. | ✅ Updated to `checkout@v7` and `setup-python@v6` (Node 24). |

---

## "Gemini answered 401 UNAUTHENTICATED for every model"

1. Go to **https://aistudio.google.com/api-keys** and sign in.
2. Click **Create API key**. New keys are "auth keys" and start with **`AQ.`**.
3. GitHub → **Settings → Secrets and variables → Actions → `GEMINI_API_KEY` → Update**, and paste the new key. Paste only the key: no quotes, no spaces.
4. Run the workflow with task **doctor**. You should see `✅ AI: gemini  model gemini-3.x-flash responded`.

Still 401 with a fresh `AQ.` key? Some Google accounts have had problems with the new key rollout — as of
September 2026 there are multiple open reports where even AI Studio's own cURL snippet returns
`401 ACCESS_TOKEN_TYPE_UNSUPPORTED` for a brand-new `AQ.` key. Work through this checklist:

1. **Restrict the key.** Cloud Console → APIs & Services → Credentials → the key → *API restrictions* →
   *Restrict key* → allow only **Gemini API**. Unrestricted keys are being rejected.
2. **Check the API is enabled** for that project (*Generative Language API*), or skip the question entirely:
   in AI Studio use **Create API key in new project** and use that key instead.
3. **Prove where the fault is.** Copy AI Studio's own cURL snippet for the key and run it. If that also
   returns 401, the problem is on Google's side for that account/project — no code change can fix it.
   (This bot already sends the key exactly as Google documents: `x-goog-api-key` header on
   `generativelanguage.googleapis.com/v1beta`, never `Authorization: Bearer`, never a `?key=` query
   parameter — both of which are rejected for `AQ.` keys.)
4. **Add a second free provider** so the site keeps publishing full AI articles regardless:

* **Groq**: https://console.groq.com/keys → secret `GROQ_API_KEY` (free tier: about 1,000 requests/day on gpt-oss models)
* **OpenRouter**: https://openrouter.ai/settings/keys → secret `OPENROUTER_API_KEY` (uses the free `openrouter/free` router)

When a provider fails, the bot switches to the next one automatically. It pauses a broken provider for 6 hours, or until you change its key.

### Confirmed behaviour in CI (2026-09-23, run 35844002428)

The Gemini secret on this repository is an `AQ.` key (53 chars) and Google answers
`401 ACCESS_TOKEN_TYPE_UNSUPPORTED` for all seven models. The run therefore did this, in 17 seconds:

```text
📝 Connecting to Blogger   Blog: BSDC News (https://news.bsdc.info.bd) — 150 recent posts indexed for de-duplication
📡 Fetching feeds          15/15 feeds ✓ — 210 items
📈 Trends                  40 trending terms loaded (US, BD)
🎯 20 candidates after filtering, ranking and de-duplication (budget 1)
🔑 gemini authentication failed — provider disabled for this run   ← the only real error
✅ LIVE [brief · quality 100 · 195 words · Mobile] https://news.bsdc.info.bd/2026/09/the-iphone-duos-under-display-camera-is.html
📡 WebSub hubs notified (4)
🏁 Done in 17s — published 1, skipped 0, failed 0, exit code 1
```

So: **publishing works end-to-end.** The post went out through the extractive news-brief writer (labelled
"News Brief"), and the run is red *only* to tell you the AI key needs attention — under v5 the identical
situation reported ✅ success while publishing nothing. Add a working AI key (steps above) and the same run
publishes full AI-written articles instead of briefs.

## Blogger: `invalid_grant` / "Google OAuth refresh failed"

Your refresh token expired or was revoked. The most common reason is that the OAuth consent screen is still in **Testing**, where tokens die after 7 days.

1. Google Cloud Console → **APIs & Services → OAuth consent screen** → **Publish app** (set it to "In production").
2. Create a new token on your computer:
   `python scripts/get_refresh_token.py --client-id … --client-secret …`
3. Update the `GOOGLE_REFRESH_TOKEN` secret.

## Blogger: 403 forbidden

The Google account that created the refresh token must be an admin or author of the blog, and `BLOG_ID` must be the numeric ID. You can find it in the Blogger dashboard URL after `blogID=`.

## Google Indexing API: 403 permission denied

Add the service-account e-mail (shown by the doctor) as an **Owner** of your property in **Google Search Console → Settings → Users and permissions**. Also enable the **Web Search Indexing API** in the service account's Cloud project.

## IndexNow "skipped (no verified key)"

IndexNow requires a key file on your domain. A plain `*.blogspot.com` blog cannot host one, so the bot skips it automatically. See `docs/SEO.md` for the custom-domain setup.

## Nothing gets published, but the run is green

This is intentional when there was nothing new to publish: every candidate was already published, filtered, or the daily limit was reached. Open the run's **Summary** tab to see the "Filtered candidates" table.

## Where is the state/history?

It is on the **`bot-data`** branch (`state.json`, `reports/`, `index.html` dashboard). Deleting that branch resets the bot. If that happens, the bot rebuilds its memory from the last 60 blog posts, so stories are not re-published.
