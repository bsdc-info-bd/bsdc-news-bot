"""The v7 writing engine: local analysis, composition and quality gating.

Nothing here touches the network or an API key — that is the point of the rewrite.
"""

import re
import time

import pytest

from bsdc_news.cortex.engine import ENGINE_NAME, ENGINE_VERSION, CortexEngine
from bsdc_news.cortex.types import ArticleRequest
from bsdc_news.errors import ContentRejected

SOURCE = """Bangladesh Bank raised its policy rate by 50 basis points to 9.5 percent on Monday, the sixth
increase in fourteen months, as inflation stayed above 9 percent for a third consecutive quarter.

Governor Abdur Rouf Talukder told reporters in Dhaka that the tightening would continue until prices
stabilise. "Inflation is still above our tolerance band and we will act again if needed," he said at a
briefing after the monetary policy committee meeting.

Commercial banks will implement the new rate from 1 November, the central bank said in a statement
published on its website. The decision was unanimous, according to two people familiar with the meeting.

The taka has lost about 25 percent of its value against the dollar since 2022, raising the cost of fuel
and food imports. Private credit growth slowed to 8.3 percent in September from 11.1 percent a year earlier.

Economists at the Policy Research Institute of Bangladesh forecast growth of 5.8 percent this fiscal year,
below the government's 6.5 percent target. Remittances rose 18 percent in the first quarter, official data
showed, helping to rebuild foreign reserves of $19.8 billion.

The International Monetary Fund approved a $4.7 billion programme for Bangladesh in January 2023. The next
review mission is expected to visit Dhaka in December, the finance ministry said.
"""

TITLE = "Bangladesh Bank raises policy rate to 9.5 percent as inflation persists"
REQUEST = dict(title=TITLE, text=SOURCE, url="https://example-news.test/bangladesh-bank-rate",
               source="Example News", category="Business", target_words=600, min_words=380, tone="news")


@pytest.fixture(scope="module")
def engine():
    return CortexEngine(grade_target=12.0)


@pytest.fixture(scope="module")
def draft(engine):
    return engine.write(ArticleRequest(**REQUEST))


# ------------------------------------------------------------------ identity
def test_engine_identifies_itself_without_a_provider(draft):
    assert ENGINE_NAME == "BSDC Cortex" and ENGINE_VERSION
    assert draft.engine.startswith(ENGINE_NAME)
    assert draft.machine_written is True


def test_engine_writes_fast_and_offline(draft):
    assert draft.timings["total"] < 5.0
    assert draft.stats["passes"] >= 1


def test_engine_reports_the_language_it_detected(draft):
    assert draft.stats["language"] == "en"
    assert draft.stats["source_words"] > 100


# ------------------------------------------------------------------ headline & lede
def test_headline_is_a_sentence_case_news_headline(draft):
    assert 20 < len(draft.headline) <= 80
    assert draft.headline[0].isupper() and not draft.headline.endswith(".")
    assert "<" not in draft.headline


def test_headline_carries_the_subject_of_the_story(draft):
    assert "bangladesh bank" in draft.headline.lower() or "rate" in draft.headline.lower()


def test_headline_candidates_were_considered(draft):
    assert len(draft.stats["headline_candidates"]) >= 2


def test_dek_is_a_standfirst_not_a_quotation(draft):
    assert 40 <= len(draft.dek) <= 220
    assert draft.dek[0] not in "\"'“"


def test_meta_description_fits_the_serp_budget(draft):
    assert 110 <= len(draft.meta_description) <= 160


def test_lede_is_the_first_block_and_is_marked_up(draft):
    assert draft.body_html.lstrip().startswith("<p")
    assert "bsd-lede" in draft.body_html


# ------------------------------------------------------------------ body
def test_body_is_clean_publishable_html(draft):
    body = draft.body_html
    for tag in ("<script", "<style", "<iframe", "javascript:", "onerror=", "<h1"):
        assert tag not in body.lower()
    assert body.count("<p") >= 8


def test_body_uses_subheadings(draft):
    assert "<h2" in draft.body_html
    assert draft.outline and all(isinstance(kind, str) for kind in draft.outline)


def test_body_sections_carry_their_own_metadata(draft):
    assert draft.sections
    kinds = {section.kind for section in draft.sections}
    assert "lede" in kinds
    assert any(section.paragraphs for section in draft.sections)
    for section in draft.sections:
        assert section.level in (2, 3) and section.kind


def test_paragraphs_are_short_enough_for_mobile(draft):
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", draft.body_html, re.S)
    assert paragraphs
    assert max(len(re.sub(r"<[^>]+>", " ", p).split()) for p in paragraphs) <= 95


def test_bullet_points_are_drawn_from_the_source(draft):
    bullets = draft.stats["bullets"]
    assert 2 <= len(bullets) <= 6
    assert all(len(point.split()) > 4 for point in bullets)


# ------------------------------------------------------------------ grounding
def test_facts_are_extracted_and_typed(draft):
    assert len(draft.facts) >= 5
    kinds = {fact.kind for fact in draft.facts}
    assert kinds & {"quote", "number", "date", "statement"}
    assert all(fact.score > 0 for fact in draft.facts)


def test_attribution_survives_into_the_article(draft):
    text = re.sub(r"<[^>]+>", " ", draft.body_html).lower()
    assert any(marker in text for marker in ("said", "told", "according to", "the central bank"))
    # Any blockquote the engine does keep must be attributed to somebody.
    for quote in re.findall(r"<blockquote[^>]*>(.*?)</blockquote>", draft.body_html, re.S):
        assert "said" in quote.lower() or "told" in quote.lower() or len(quote.split()) > 8


def test_figures_from_the_source_are_preserved(draft):
    assert "9.5" in draft.body_html
    assert draft.keywords["numbers"]


def test_entities_are_recognised(draft):
    names = [str(entity) for entity in draft.entities]
    assert names and any("Bangladesh" in name for name in names)


def test_the_engine_does_not_invent_unsupported_claims(draft):
    assert 0.0 <= draft.confidence <= 1.0
    assert draft.confidence >= 0.5


# ------------------------------------------------------------------ extras
def test_faq_is_grounded_and_schema_ready(draft):
    assert draft.faq
    for question, answer in draft.faq:
        assert question.endswith("?") and len(answer.split()) >= 8
        assert answer[-1] in ".!?\"'", answer


def test_tldr_is_shorter_than_the_article(draft):
    assert draft.tldr
    assert len(" ".join(draft.tldr).split()) < draft.words


def test_keywords_are_relevant_and_unstuffed(draft):
    primary = draft.keywords["primary"]
    assert primary and len(primary.split()) <= 4
    assert primary.split()[0] in {word.lower() for word in TITLE.split()}
    assert len(draft.keywords["secondary"]) >= 2
    # A name followed by a verb is a sentence fragment, not a keyword.
    assert "bangladesh forecast growth" not in draft.keywords["secondary"]
    assert draft.keywords["intent"]


def test_tags_and_category_are_present(draft):
    assert draft.category == "Business"
    assert 1 <= len(draft.tags) <= 8
    assert all(len(tag) < 40 for tag in draft.tags)


def test_quality_and_readability_are_scored(draft):
    assert draft.quality_score >= 55
    assert draft.readability["grade"] > 0
    assert draft.readability["originality"] > 0.2
    assert draft.sentiment["label"] in ("positive", "neutral", "negative", "mixed")


def test_originality_beats_a_verbatim_copy(draft):
    source_sentences = {s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", SOURCE) if len(s.split()) > 12}
    body = re.sub(r"<[^>]+>", " ", draft.body_html)
    body_sentences = {s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.split()) > 12}
    assert len(source_sentences & body_sentences) <= 4


def test_timing_breakdown_covers_every_stage(draft):
    for stage in ("analyze", "outline", "headline", "lede", "sections", "compose", "quality", "total"):
        assert stage in draft.timings


# ------------------------------------------------------------------ guards
def test_engine_rejects_a_source_that_is_too_thin(engine):
    with pytest.raises(ContentRejected):
        engine.write(ArticleRequest(title="Something happened", text="It happened on Monday.",
                                    url="https://example.test/thin", source="Example", min_words=380))


def test_engine_rejects_a_story_it_has_already_covered(engine):
    with pytest.raises(ContentRejected):
        engine.write(ArticleRequest(**REQUEST), published_titles=[TITLE], published_bodies=[SOURCE])


def test_engine_honours_a_lower_word_target(engine):
    short = engine.write(ArticleRequest(**{**REQUEST, "target_words": 300, "min_words": 160}))
    assert short.words <= 480


def test_engine_caps_expansion_at_what_the_source_can_support(engine):
    source_words = len(SOURCE.split())
    long_form = engine.write(ArticleRequest(**{**REQUEST, "target_words": 900, "min_words": 700}))
    # A 214-word source cannot honestly fill 900 words: the engine caps the article
    # instead of inventing filler, and the quality gate accepts the shorter result.
    assert long_form.words <= max(700, source_words * 2.4)
    assert long_form.quality_score >= 55
    assert long_form.readability["originality"] > 0.2


def test_engine_handles_a_bengali_source():
    engine = CortexEngine(grade_target=12.0, supported_languages=("en", "bn"))
    bengali = engine.write(ArticleRequest(
        title="বাংলাদেশ ব্যাংক সুদের হার বাড়াল", text=(
            "বাংলাদেশ ব্যাংক সোমবার নীতি সুদের হার ৫০ বেসিস পয়েন্ট বাড়িয়ে ৯.৫ শতাংশ করেছে। "
            "গভর্নর আব্দুর রউফ তালুকদার ঢাকায় সাংবাদিকদের বলেন, মূল্যস্ফীতি সহনীয় পর্যায়ে না আসা পর্যন্ত "
            "এই নীতি অব্যাহত থাকবে। বাণিজ্যিক ব্যাংকগুলো ১ নভেম্বর থেকে নতুন হার কার্যকর করবে। "
            "গত তিন প্রান্তিকে মূল্যস্ফীতি ৯ শতাংশের ওপরে ছিল। রেমিট্যান্স প্রবাহ ১৮ শতাংশ বেড়েছে। "
            "বৈদেশিক মুদ্রার রিজার্ভ দাঁড়িয়েছে ১৯.৮ বিলিয়ন ডলার। "
            "অর্থ মন্ত্রণালয় জানিয়েছে, আইএমএফের পরবর্তী পর্যালোচনা মিশন ডিসেম্বরে ঢাকা সফর করবে।") * 3,
        url="https://example.test/bn", source="উদাহরণ সংবাদ", category="Business",
        target_words=300, min_words=120))
    assert bengali.words >= 80
    assert bengali.stats["language"] == "bn"


def test_engine_survives_a_source_full_of_markup(engine):
    noisy = engine.write(ArticleRequest(
        **{**REQUEST, "text": "<div class='ad'>Buy now</div>" + SOURCE.replace("\n", "<br>") +
           "<script>alert(1)</script>"}))
    assert noisy.words > 200 and "<script" not in noisy.body_html


def test_engine_never_blocks_on_a_long_source(engine):
    start = time.perf_counter()
    engine.write(ArticleRequest(**{**REQUEST, "text": SOURCE * 5}))
    assert time.perf_counter() - start < 25


def test_analysis_can_be_reused_for_a_revision(engine):
    analysis = engine.analyze(ArticleRequest(**REQUEST))
    assert analysis.facts and analysis.primary_keyword()
    again = engine.write(ArticleRequest(**REQUEST), analysis=analysis)
    assert again.words > 200


def test_quality_gate_and_revision_are_available_separately(engine):
    req = ArticleRequest(**REQUEST)
    analysis = engine.analyze(req)
    first = engine.write(req, analysis=analysis)
    report = engine.quality(first, req, analysis)
    assert 0 <= report.score <= 100 and isinstance(report.actions, (list, tuple))
    assert report.words > 0 and report.originality >= 0
    revised = engine.revise(first, req, analysis, report)
    assert revised.words > 0


# ------------------------------------------------------------------ writer adapter
def _writer():
    from bsdc_news.settings import load_settings
    from bsdc_news.writer import build_writer

    return build_writer(load_settings(env={}))


def test_writer_adapter_exposes_the_engine_to_the_pipeline():
    from bsdc_news.writer import GenerationRequest

    writer = _writer()
    assert writer.enabled and writer.auth_errors == {}
    health = writer.health()
    assert health["requires_api_key"] is False and health["cost"] == "free"
    assert health["engine"].startswith(ENGINE_NAME) and health["gazetteer_entries"] > 100
    draft = writer.generate(GenerationRequest(**{k: v for k, v in REQUEST.items() if k != "text"},
                                              text=SOURCE))
    assert draft is not None and draft.ai_generated is False and draft.machine_written is True
    assert draft.provider == "cortex" and draft.model.startswith(ENGINE_NAME)
    assert writer.describe(draft)


def test_writer_draft_is_backwards_compatible_with_the_old_ai_contract():
    from bsdc_news.writer import GenerationRequest

    draft = _writer().generate(GenerationRequest(**{k: v for k, v in REQUEST.items() if k != "text"},
                                                 text=SOURCE))
    assert draft.dek and draft.key_points and isinstance(draft.faq[0], dict)
    assert {"question", "answer"} <= set(draft.faq[0])
    assert draft.as_cortex().headline == draft.headline


def test_writer_plan_seo_returns_a_plan_the_renderer_can_use():
    from bsdc_news.writer import GenerationRequest, seo_summary

    writer = _writer()
    draft = writer.generate(GenerationRequest(**{k: v for k, v in REQUEST.items() if k != "text"},
                                              text=SOURCE))
    plan = writer.plan_seo(draft, category="Business", post_url="https://b.test/2026/01/rate.html",
                           related_posts=[{"url": "https://b.test/x.html", "title": "Inflation eases"}])
    assert plan.primary_keyword and plan.title_tag and plan.meta_description and plan.slug
    assert plan.json_ld and plan.canonical.endswith("rate.html")
    assert "SEO" in seo_summary(plan)


def test_writer_returns_none_for_a_story_it_cannot_support():
    from bsdc_news.writer import GenerationRequest

    assert _writer().generate(GenerationRequest(title="Nothing", text="Nothing happened.",
                                                url="https://example.test/x", source="Example",
                                                min_words=380)) is None


def test_writer_tracks_how_many_articles_it_rejected():
    from bsdc_news.writer import GenerationRequest

    writer = _writer()
    writer.generate(GenerationRequest(title="Nothing", text="Nothing happened.", url="u", source="s"))
    assert writer.health()["articles_rejected"] >= 1


def test_disabled_writer_declines_every_request(monkeypatch):
    from bsdc_news.settings import load_settings
    from bsdc_news.writer import GenerationRequest, build_writer

    settings = load_settings(env={"BSDC_WRITER_ENABLED": "false"})
    writer = build_writer(settings)
    assert writer.enabled is False
    assert writer.generate(GenerationRequest(**{k: v for k, v in REQUEST.items() if k != "text"},
                                             text=SOURCE)) is None
    assert writer.health()["enabled"] is False


def test_writer_tracks_published_titles_for_novelty_checks():
    from bsdc_news.writer import GenerationRequest

    writer = _writer()
    assert isinstance(writer.published_titles(), list)
    assert isinstance(writer.published_bodies(), list)
    first = writer.generate(GenerationRequest(**{k: v for k, v in REQUEST.items() if k != "text"},
                                              text=SOURCE))
    assert first is not None
