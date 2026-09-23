Rewrite the SOURCE MATERIAL below into an original, fully structured news article for {site}.

RULES
1. Facts only from the source. Never invent quotes, numbers, names, dates or events. If something is uncertain, attribute it ("according to {source}").
2. Write {target_words}-{max_words} words in fresh wording — do not copy sentences verbatim (short attributed quotes are fine).
3. Journalistic structure: inverted pyramid. Start with a strong lead paragraph (who/what/when/where/why), then 3-5 <h2> sections such as "Key Details", "Background", "Why It Matters", "What's Next". Use <h3>, <ul>/<ol> and a comparison <table> only when they genuinely help.
4. Allowed HTML tags only: <p> <h2> <h3> <ul> <ol> <li> <strong> <em> <blockquote> <mark> <table> <thead> <tbody> <tr> <th> <td>. No links, no images, no inline styles, no markdown, no <h1>.
5. Remove promotional text, affiliate/deal mentions, newsletter prompts, author bios and the original site's self-references.
6. Highlight at most 2 essential facts with <mark>.
7. Headline: specific and factual, max 90 characters, no clickbait, no ALL CAPS, no trailing period.
8. meta_description: 140-160 characters summarising the news for search results.
9. key_points: 3-5 short factual bullet strings (max 20 words each).
10. faq: 2-3 question/answer pairs readers would search for, answered only from the source.
11. tags: 3-6 short topic tags (companies, products, technologies). category: exactly one of {categories}.
12. focus_keyword: the main 2-4 word search phrase.

Return ONLY this JSON object (no markdown fences):
{{"headline": "...", "meta_description": "...", "focus_keyword": "...", "category": "...",
 "tags": ["..."], "key_points": ["..."], "body_html": "<p>...</p>",
 "faq": [{{"q": "...", "a": "..."}}]}}

ORIGINAL HEADLINE: {title}
SOURCE: {source}
PUBLISHED: {published}
OTHER OUTLETS COVERING THIS STORY: {related}

SOURCE MATERIAL:
<<<
{text}
>>>
