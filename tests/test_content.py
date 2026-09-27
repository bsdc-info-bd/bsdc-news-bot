import json
import re

from bsdc_news.brief import build_brief, split_sentences, summarize
from bsdc_news.content.quality import assess, overlap_ratio, unsupported_numbers
from bsdc_news.content.render import RenderInput, build_post_html
from bsdc_news.content.sanitize import sanitize_html, strip_markdown
from bsdc_news.content.seo import clean_headline, faq_schema, meta_description
from bsdc_news.content.taxonomy import Taxonomy
from bsdc_news.extractor import ImageCandidate, parse_article

from .conftest import good_body


def test_sanitizer_removes_scripts_events_and_bad_urls():
    dirty = ('<h1>Title</h1><p onclick="x()">Hi <a href="javascript:alert(1)">bad</a> '
             '<a href="https://ok.com">ok</a></p><script>alert(1)</script><iframe src="x"></iframe>'
             '<p></p><img src="https://x.com/a.jpg" onerror="alert(1)"><div style="background:url(x)">t</div>')
    clean = sanitize_html(dirty)
    assert "<script" not in clean and "iframe" not in clean and "onclick" not in clean
    assert "javascript:" not in clean and "<img" not in clean and "url(" not in clean
    assert "<h2>Title</h2>" in clean
    assert 'href="https://ok.com"' in clean and 'rel="nofollow noopener"' in clean
    assert "<p></p>" not in clean
    assert "ok" in sanitize_html('<a href="https://ok.com">ok</a>', allow_links=False)
    assert "<a" not in sanitize_html('<a href="https://ok.com">ok</a>', allow_links=False)


def test_strip_markdown():
    assert strip_markdown("## Heading\n**bold** and *em*") == "<h2>Heading</h2>\n<strong>bold</strong> and <em>em</em>"


def test_quality_gate_scores_good_and_bad_drafts(article_html):
    source = parse_article(article_html, "https://example-tech.com/x").text
    good = assess(good_body(650), source, min_words=450, target_words=750)
    assert good.passed, good.issues
    short = assess("<p>Too short.</p>", source)
    assert not short.passed and any("too short" in i for i in short.issues)
    leak = assess(good_body(650) + "<p>As an AI language model I cannot verify this.</p>", source)
    assert leak.score < good.score and any("leaked" in i for i in leak.issues)
    copied = assess("".join(f"<p>{p}</p>" for p in source.split("\n")) + "<h2>A</h2><h2>B</h2>", source)
    assert any("copies the source" in i or "overlap" in i for i in copied.issues)


def test_overlap_and_unsupported_numbers():
    src = "The company shipped 5.2 million units in 2026 and revenue grew 12 percent to 3,400 dollars."
    assert overlap_ratio(src, src) == 1.0
    assert overlap_ratio("Completely different words here about another topic entirely now ok", src) == 0.0
    assert unsupported_numbers("It shipped 5.2 million units, up 12 percent.", src) == set()
    assert unsupported_numbers("It shipped 9.9 million units worth 77 dollars.", src) == {"9.9", "77"}


def test_brief_writer_is_extractive_attributed_and_safe(article_html):
    art = parse_article(article_html, "https://example-tech.com/x")
    sents = split_sentences(art.text)
    assert len(sents) > 8
    summary = summarize(art.text, "Nvidia unveils Rubin Ultra", 4)
    assert len(summary) == 4 and all(s in sents for s in summary)
    draft = build_brief("Nvidia unveils <Rubin> Ultra", art.text, "Example Tech", "https://example-tech.com/x",
                        description=art.description, related=["The Verge"])
    assert not draft.ai_generated and draft.provider == "brief"
    assert "Example Tech reports" in draft.body_html and "https://example-tech.com/x" in draft.body_html
    assert "<h2>Key Points</h2>" in draft.body_html and "The Verge" in draft.body_html
    q = assess(sanitize_html(draft.body_html), art.text, ai_generated=False)
    assert q.passed, q.issues


def test_taxonomy_classifies_and_builds_labels(settings):
    t = Taxonomy(settings)
    assert t.classify("Hackers exploit zero-day flaw in routers", "") == "Cybersecurity"
    assert t.classify("OpenAI launches GPT-6 with better reasoning", "") == "AI"
    assert t.classify("Grameenphone expands 5G in Dhaka", "") == "Bangladesh"
    assert t.classify("Something vague happened", "", hint="Gadgets") == "Gadgets"
    labels = t.labels("Nvidia unveils Rubin Ultra AI chip", "Microsoft and Google are customers", "AI",
                      ["AI chips", "data centers", "Nvidia"])
    assert labels[0] == "Tech News" and "AI" in labels and "Nvidia" in labels
    assert len(labels) <= 6 and len({x.lower() for x in labels}) == len(labels)


def test_seo_helpers():
    assert clean_headline("BREAKING: Apple Launches New Mac - TechCrunch") == "Apple Launches New Mac"
    assert clean_headline("NVIDIA SHARES SOAR AFTER EARNINGS") == "Nvidia Shares Soar After Earnings"
    assert len(meta_description("short", "A " * 200)) <= 158
    assert faq_schema([{"q": "a", "a": "b"}]) is None
    assert faq_schema([{"q": "a", "a": "b"}, {"q": "c", "a": "d"}])["@type"] == "FAQPage"


def test_render_full_post_has_schema_images_attribution(settings):
    hero = ImageCandidate(url="https://cdn.x.com/h.jpg", origin="og", width=1600, height=900)
    inline = ImageCandidate(url="https://cdn.x.com/i.jpg", origin="article", caption="Board", credit="Nvidia")
    inp = RenderInput(headline='Nvidia "Rubin" <Ultra>', body_html=good_body(), meta_description="desc",
                      category="AI", labels=["Tech News", "AI"], source_name="Example Tech",
                      source_url="https://example-tech.com/x", words=650,
                      images=[(hero, "https://wsrv.nl/?url=h"), (inline, "https://wsrv.nl/?url=i")],
                      key_points=["Doubles efficiency"], faq=[{"q": "When?", "a": "2027."}, {"q": "Who?", "a": "Nvidia"}],
                      related_posts=[{"title": "Older post", "url": "https://bsdcnews.blogspot.com/old.html"}],
                      related_sources=["The Verge"])
    html = build_post_html(inp, settings, post_url="https://bsdcnews.blogspot.com/2026/09/p.html")
    blocks = re.findall(r'<script type="application/ld\+json">(.+?)</script>', html)
    schemas = [json.loads(b) for b in blocks]
    types = {s["@type"] for s in schemas}
    assert {"NewsArticle", "FAQPage"} <= types
    article = next(s for s in schemas if s["@type"] == "NewsArticle")
    assert article["@context"] == "https://schema.org" and article["url"].endswith("/p.html")
    assert article["isBasedOn"] == "https://example-tech.com/x"
    assert "&lt;Ultra&gt;" in html and "<Ultra>" not in html.replace("&lt;Ultra&gt;", "")
    body_start = html.index('class="bsdc-article"')
    assert html.index('src="https://wsrv.nl/?url=i"') > html.index("</h2>", body_start)  # inline image after 1st h2
    assert html.index('src="https://wsrv.nl/?url=h"') < html.index("</h2>", body_start)  # hero before the body
    assert "Key Takeaways" in html and "Frequently Asked Questions" in html
    assert "Read the original article" in html and "Also covered by The Verge" in html
    assert "facebook.com/sharer" in html and "Older post" in html
    assert "compiled automatically" in html and "No external AI service" in html
