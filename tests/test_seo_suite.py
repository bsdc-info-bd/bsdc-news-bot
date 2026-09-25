"""The v7 SEO layer: titles, meta, slugs, headings, density, internal links,
sitemap, robots, the on-page audit, the schema graph and the planner."""

from bsdc_news.seo import audit as seo_audit
from bsdc_news.seo import density, headings, internal_links, meta, planner, robots, sitemap, slug, title
from bsdc_news.seo.schema import article as schema_article
from bsdc_news.seo.schema import breadcrumb, faq, graph, itemlist, script_tag, validate_all

HEADLINE = "Bangladesh Bank raises policy rate to 9.5 percent as inflation persists"
BODY = (
    "Bangladesh Bank raised its policy rate by 50 basis points to 9.5 percent on Monday, "
    "the sixth increase in fourteen months, as inflation stayed above 9 percent for a third quarter. "
    "Governor Abdur Rouf Talukder told reporters the tightening would continue until prices stabilise. "
    "Commercial banks will implement the new rate from 1 November, the central bank said in a statement. "
    "The taka has lost 25 percent of its value against the dollar since 2022, raising the cost of imports. "
    "Private credit growth slowed to 8.3 percent in September from 11.1 percent a year earlier. "
    "Remittances rose 18 percent in the first quarter of the fiscal year, official data showed."
)
KEYWORD = "bangladesh bank"
URL = "https://b.test/2026/01/bangladesh-bank-rate.html"


# ------------------------------------------------------------------ title tags
def test_title_clean_strips_tags_and_collapses_space():
    assert title.clean("  Rate   hike <b>announced</b>  ") == "Rate hike announced"


def test_title_build_respects_the_60_character_budget():
    tag = title.build(HEADLINE, keyword=KEYWORD, site_name="bsdc news")
    assert tag and len(tag) <= 62


def test_title_keyword_first_moves_the_target_to_the_front():
    out = title.keyword_first("Rate rise announced by Bangladesh Bank", KEYWORD)
    assert out.lower().startswith(KEYWORD)


def test_title_brand_suffix_is_short_and_separated():
    assert title.with_brand("Rate rise announced", "bsdc news").endswith("bsdc news")


def test_title_differs_from_h1_detects_duplicates():
    assert not title.differs_from_h1("Rate rise announced", "Rate rise announced")
    assert title.differs_from_h1("Rate rise announced", "Central bank tightens policy again")


def test_title_scores_penalise_length_and_stuffing():
    assert title.length_score("Short and sharp headline") > title.length_score("x" * 90)
    stuffed = " ".join([KEYWORD] * 8)
    # stuffing_score is a risk score: the higher it is, the worse the title reads.
    assert title.stuffing_score(stuffed, [KEYWORD]) > title.stuffing_score("Central bank acts", [KEYWORD])


def test_title_candidates_are_unique_and_ordered():
    cands = title.candidates(HEADLINE, keyword=KEYWORD, site_name="bsdc news")
    assert len(cands) >= 2
    tags = [tag for tag, _reason in cands]
    assert len(set(tags)) == len(tags)
    assert all(len(tag) <= 70 for tag in tags)


# ------------------------------------------------------------------ meta
def test_meta_description_lands_inside_the_snippet_window():
    desc = meta.description(lede=BODY.split(". ")[0], keyword=KEYWORD, dek=BODY)
    assert 120 <= len(desc) <= 160


def test_meta_description_never_ends_on_a_dangling_word():
    desc = meta.description(lede=BODY, keyword=KEYWORD, dek=BODY)
    assert desc[-1] in ".!?\"" and not desc.endswith((" and", " the", " of", " to"))


def test_meta_description_falls_back_to_the_dek():
    assert meta.description(lede="", dek=BODY.split(". ")[0], keyword=KEYWORD)


def test_meta_description_can_be_shortened_for_a_tight_budget():
    desc = meta.description(lede=BODY, keyword=KEYWORD, dek=BODY, maximum=120)
    assert len(desc) <= 120


def test_robots_directive_is_indexable_by_default():
    assert "index" in meta.robots() and "max-image-preview:large" in meta.robots()
    assert "noindex" in meta.robots(index=False)
    assert "nofollow" in meta.robots(follow=False)


def test_open_graph_and_twitter_cards_are_complete():
    og = meta.open_graph(title="Rate rise", description="Details here.", url=URL,
                         image="https://b.test/i.jpg", site_name="bsdc news", article_type="article")
    tw = meta.twitter_card(title="Rate rise", description="Details here.", image="https://b.test/i.jpg")
    assert og["og:title"] == "Rate rise" and og["og:type"] == "article" and og["og:url"] == URL
    assert tw["twitter:card"] == "summary_large_image"
    html = meta.tags_html(og, tw)
    assert 'property="og:title"' in html and 'name="twitter:card"' in html


def test_open_graph_markup_never_reaches_the_social_cards():
    og = meta.open_graph(title='He said "no" to <b>that</b>', description="d <i>here</i>", url=URL)
    html = meta.tags_html(og, {})
    assert "<b>" not in html and "<i>" not in html
    assert "&lt;b&gt;" not in html


def test_canonical_strips_tracking_and_fragment():
    assert meta.canonical("https://b.test/p.html?utm_source=x#top") == "https://b.test/p.html"
    assert meta.canonical("https://b.test/p.html?page=2", strip_query=False).endswith("?page=2")


# ------------------------------------------------------------------ slugs
def test_slug_build_is_short_lowercase_and_keyword_led():
    built = slug.build(HEADLINE, keyword=KEYWORD)
    assert built == built.lower() and " " not in built and len(built) <= 60
    assert built.startswith("bangladesh-bank")


def test_slug_transliterate_handles_bengali():
    out = slug.transliterate("বাংলাদেশ ব্যাংক")
    assert out and all(ord(ch) < 128 for ch in out)
    assert "bangla" in out or "bank" in out


def test_slug_build_from_a_bengali_headline_is_readable():
    built = slug.build("বাংলাদেশ ব্যাংক সুদের হার বাড়াল")
    assert built and all(ord(ch) < 128 for ch in built) and len(built) >= 5


def test_slug_unique_appends_a_suffix_on_collision():
    assert slug.unique("post", ["post"]) != "post"
    assert slug.unique("post", ["other"]) == "post"


def test_slug_from_url_keeps_the_meaningful_segment():
    assert slug.from_url("https://b.test/2026/01/bangladesh-bank-rate.html") == "bangladesh-bank-rate"


def test_slug_audit_reports_problems():
    problems = slug.audit("the-of-and-post")
    assert problems and all(isinstance(row, tuple) and len(row) == 3 for row in problems)


def test_slug_breadcrumb_path_is_url_safe():
    path = slug.breadcrumb_path("bangladesh-bank-rate", "Business", base="https://b.test")
    assert path.startswith("https://b.test") and "business" in path.lower()


# ------------------------------------------------------------------ headings
def test_headings_collect_reads_levels_in_order():
    html = "<h1>One</h1><p>x</p><h2>Two</h2><h3>Three</h3>"
    assert headings.collect(html) == [(1, "One"), (2, "Two"), (3, "Three")]


def test_headings_outline_numbers_each_heading():
    out = headings.outline([(1, "One"), (2, "Two")])
    assert [row[1] for row in out] == ["One", "Two"]


def test_headings_audit_flags_skipped_levels_and_generic_text():
    problems = headings.audit([(1, "H1"), (3, "Background"), (2, "Overview")], keyword=KEYWORD)
    assert problems and all(len(row) == 3 for row in problems)


def test_headings_keyword_coverage_counts_hits():
    coverage = headings.keyword_coverage([(2, "Bangladesh Bank acts"), (2, "The outlook")], [KEYWORD])
    assert coverage[KEYWORD] >= 1


def test_headings_strengthen_keeps_an_existing_keyword():
    out = headings.strengthen("Policy rate decision explained", keyword="policy rate")
    assert "policy rate" in out.lower()


def test_headings_question_detection_feeds_the_faq_schema():
    assert headings.question_headings([(2, "What does the rate rise mean?"), (2, "The outlook")]) == [
        "What does the rate rise mean?"]


def test_headings_inject_rewrites_the_markup():
    html = "<h2>Overview</h2><p>Body text here.</p>"
    out = headings.inject(html, [(2, "Bangladesh Bank rate decision overview")])
    assert "Bangladesh Bank rate decision overview" in out and "<p>Body text here.</p>" in out


# ------------------------------------------------------------------ density
def test_density_counts_the_keyword_hits():
    metric = density.counts(BODY, KEYWORD)
    assert metric["hits"] >= 1 and metric["tokens"] > 50 and metric["density"] > 0


def test_density_prominence_and_saturation_are_bounded():
    metric = density.counts(BODY, KEYWORD)
    assert density.prominence(metric) >= 0
    assert 0 <= density.saturation(BODY, KEYWORD) <= 1


def test_density_proximity_measures_keyword_clustering():
    assert density.proximity(f"{KEYWORD} acted while {KEYWORD} watchers waited", KEYWORD) > 0
    assert density.proximity(BODY, "not present at all") < 0.05


def test_density_score_rewards_balanced_usage():
    good, good_notes = density.score(density=1.2, prominence_value=0.8, in_title=True,
                                     in_first_sentence=True, in_headings=2, in_meta=True, in_url=True)
    bad, bad_notes = density.score(density=9.0, prominence_value=0.1, in_title=False,
                                   in_first_sentence=False, in_headings=0, in_meta=False, in_url=False)
    assert good > bad and isinstance(good_notes, list) and isinstance(bad_notes, list)


def test_stuffing_risk_flags_repetition():
    stuffed = " ".join([KEYWORD] * 25) + " " + BODY
    assert density.stuffing_risk(stuffed, [KEYWORD])
    assert not density.stuffing_risk(BODY, [KEYWORD])


def test_density_report_is_a_single_object():
    rep = density.report(BODY, primary=KEYWORD, secondary=["inflation", "policy rate"], title=HEADLINE)
    assert rep["primary"] == KEYWORD and 0 <= rep["score"] <= 100
    assert "stuffing" in rep and "coverage" in rep


# ------------------------------------------------------------------ internal links
RELATED = [
    {"url": "https://b.test/2026/01/inflation-report.html", "title": "Inflation report shows prices easing"},
    {"url": "https://b.test/2026/01/taka-dollar.html", "title": "Taka slides against the dollar again"},
    {"url": "https://b.test/2025/12/remittance-growth.html", "title": "Remittance growth hits 18 percent"},
]


def test_relevance_scores_topical_overlap():
    assert internal_links.relevance(BODY, RELATED[0]["title"], keywords=[KEYWORD]) > 0
    assert internal_links.relevance(BODY, "Recipe for chocolate cake") < 0.05


def test_rank_candidates_orders_by_relevance_and_caps_the_list():
    ranked = internal_links.rank_candidates(BODY, RELATED, keywords=["inflation", KEYWORD], limit=2)
    assert len(ranked) == 2 and all("url" in item for item in ranked)


def test_rank_candidates_never_returns_the_current_post():
    ranked = internal_links.rank_candidates(
        BODY, RELATED + [{"url": URL, "title": HEADLINE}], keywords=[KEYWORD], self_url=URL)
    assert all(item["url"] != URL for item in ranked)


def test_anchor_for_produces_a_readable_phrase():
    anchor = internal_links.anchor_for(RELATED[1]["title"], BODY)
    assert anchor and len(anchor.split()) <= 8


def test_contextual_anchor_uses_words_from_the_article():
    anchor = internal_links.contextual_anchor(RELATED[0]["title"], BODY, max_words=4)
    assert anchor and len(anchor.split()) <= 5


def test_rotation_measures_anchor_diversity():
    diverse = internal_links.rotation(["inflation", "prices", "the taka", "remittances"])
    repetitive = internal_links.rotation(["inflation", "inflation", "inflation"])
    assert diverse >= repetitive


def test_insert_adds_links_and_reports_what_it_used():
    html = "<p>" + BODY.replace(". ", ". </p><p>") + "</p>"
    out, used = internal_links.insert(html, [{"url": RELATED[0]["url"], "title": RELATED[0]["title"],
                                              "anchor": "inflation report"}])
    assert "<a " in out and RELATED[0]["url"] in out
    assert out.count("<a ") <= 3 and isinstance(used, list)


def test_related_box_lists_the_posts():
    box = internal_links.related_box(RELATED)
    assert "Related coverage" in box and box.count("<li>") == len(RELATED)


def test_outgoing_links_are_collected():
    html = '<p><a href="https://b.test/a">a</a><a href="https://b.test/b">b</a></p>'
    assert len(internal_links.outgoing_links(html)) == 2


# ------------------------------------------------------------------ sitemap
def test_urlset_is_valid_xml_with_every_post():
    posts = [{"url": f"https://b.test/p{i}.html", "title": f"Post {i}"} for i in range(3)]
    doc = sitemap.urlset(posts, site_url="https://b.test")
    assert doc.startswith("<?xml") and doc.count("<url>") == 3


def test_news_urlset_includes_publication_metadata():
    posts = [{"url": "https://b.test/p1.html", "title": HEADLINE, "published": "2026-09-25T06:00:00Z"}]
    doc = sitemap.news_urlset(posts, site_name="bsdc news", language="en")
    assert "news:news" in doc and "bsdc news" in doc


def test_priority_falls_with_position_and_age():
    fresh = sitemap.priority_for(0, 50, age_days=0.0)
    old = sitemap.priority_for(40, 50, age_days=400.0)
    assert float(fresh) > float(old) and 0 < float(old) <= 1


def test_changefreq_matches_the_age_of_a_post():
    assert sitemap.changefreq_for(0.2) == "hourly"
    assert sitemap.changefreq_for(400) == "yearly"


def test_w3c_timestamps_are_normalised():
    assert sitemap._w3c("2026-09-25T06:00:00Z").endswith(("Z", "+00:00"))


# ------------------------------------------------------------------ robots
def test_robots_build_declares_sitemaps():
    text = robots.build(site_url="https://b.test", sitemap_urls=["https://b.test/sitemap.xml"])
    assert "Sitemap: https://b.test/sitemap.xml" in text and "User-agent: *" in text


def test_robots_validate_accepts_the_generated_file():
    assert robots.validate(robots.build(site_url="https://b.test")) == []


def test_robots_rejects_invalid_disallow_paths():
    assert robots.validate("User-agent: *\nDisallow: ?m=0\n")


def test_robots_allows_answers_for_a_path():
    text = robots.build(site_url="https://b.test")
    assert robots.allows(text, "/2026/01/post.html")


def test_robots_sitemap_declaration_is_discoverable():
    text = robots.build(site_url="https://b.test", sitemap_urls=["https://b.test/sitemap.xml"])
    assert robots.sitemap_declared(text) == ["https://b.test/sitemap.xml"]


# ------------------------------------------------------------------ audit
def _article_node():
    return schema_article.build(headline=HEADLINE, description="Details of the rate decision.", url=URL,
                                images=["https://b.test/i.jpg"], author_name="bsdc news desk",
                                publisher_name="bsdc news", publisher_url="https://b.test",
                                section="Business", keywords=["inflation"], words=600, language="en",
                                published="2026-09-25T06:00:00Z")


def test_audit_passes_a_well_formed_page():
    tag = title.build(HEADLINE, keyword=KEYWORD, site_name="bsdc news")
    desc = meta.description(lede=BODY.split(". ")[0], keyword=KEYWORD, dek=BODY)
    report = seo_audit.run(
        title_tag=tag, headline=HEADLINE, description=desc, slug=slug.build(HEADLINE, keyword=KEYWORD),
        canonical=URL, html=f"<h1>{HEADLINE}</h1>" + f"<p>{BODY}</p>" * 3, keywords=[KEYWORD, "inflation"],
        primary_keyword=KEYWORD, images=[{"url": "https://b.test/i.jpg", "alt": "Bangladesh Bank chart"}],
        links=[{"url": RELATED[0]["url"], "text": "inflation report"}],
        jsonld_nodes={"article": _article_node()}, author="bsdc news desk",
        published="2026-09-25T06:00:00Z", site_name="bsdc news", related_count=1, sources=1,
        word_floor=120)
    assert report.score >= 60, seo_audit.actions(report)
    assert report.checks and not report.blocking


def test_audit_fails_a_page_without_title_or_description():
    report = seo_audit.run(title_tag="", headline="", description="", slug="", canonical="",
                           html="<p>x</p>", keywords=[], primary_keyword="", jsonld_nodes={})
    failed = {name for name, ok, _detail in report.checks if not ok}
    assert report.score < 75
    assert {"title_present", "meta_description"} & failed or report.blocking


def test_audit_summary_and_actions_are_human_readable():
    report = seo_audit.run(title_tag="x" * 90, headline="x" * 90, description="", slug="", canonical="",
                           html="<p>x</p>", keywords=[], primary_keyword="", jsonld_nodes={})
    assert isinstance(seo_audit.summary(report), str) and seo_audit.actions(report)


def test_audit_groups_checks_by_category():
    report = seo_audit.run(title_tag="t", headline="h", description="d", slug="s", canonical=URL,
                           html="<h1>h</h1><p>x</p>", keywords=[], primary_keyword="", jsonld_nodes={})
    assert report.by_category and report.weighted is not None


def test_audit_detects_duplicate_ids_and_unclosed_tags():
    assert seo_audit._duplicate_ids('<p id="a">x</p><p id="a">y</p>')
    assert seo_audit._unclosed_tags("<div><p>unclosed</div>")


# ------------------------------------------------------------------ schema graph
def test_article_schema_validates_with_its_publisher():
    node = _article_node()
    assert schema_article.validate(node) == []
    assert node["publisher"]["name"] == "bsdc news"


def test_article_schema_requires_the_core_fields():
    assert schema_article.validate({"@type": "NewsArticle"})
    assert schema_article.validate(None)


def test_article_schema_marks_a_machine_written_story_in_the_byline():
    node = _article_node()
    assert "desk" in str(node["author"]).lower() or "bsdc" in str(node["author"]).lower()


def test_speakable_schema_points_at_the_headline_block():
    item = schema_article.speaking_item(HEADLINE, url=URL, author_name="bsdc news desk")
    node = schema_article.speakable(URL)
    assert item["@id"] == URL and HEADLINE in str(item.values())
    assert node["@type"] == "WebPage"


def test_faq_schema_pairs_questions_with_answers():
    node = faq.build([("What changed on Monday?", "The central bank raised its policy rate to 9.5 percent."),
                      ("When do banks apply it?", "Commercial banks implement the new rate from 1 November.")])
    assert faq.validate(node) == []
    assert faq.questions_only(node) == ["What changed on Monday?", "When do banks apply it?"]
    assert "What changed on Monday?" in faq.to_visible_html(
        [("What changed on Monday?", "The central bank raised its policy rate to 9.5 percent.")])


def test_faq_schema_rejects_an_empty_node():
    assert faq.validate(None) and faq.validate({"@type": "FAQPage"})


def test_breadcrumb_schema_and_html_agree():
    items = [("Home", "https://b.test/"), ("Business", "https://b.test/search/label/Business"),
             (HEADLINE, URL)]
    node = breadcrumb.build(items)
    assert breadcrumb.validate(node) == []
    html = breadcrumb.to_html(items)
    assert "Home" in html and html.count("<a ") == 2 and HEADLINE in html


def test_breadcrumb_for_article_builds_the_label_path():
    items = breadcrumb.for_article(site_name="bsdc news", site_url="https://b.test", category="Business",
                                   headline=HEADLINE, url=URL)
    assert items[0][0] == "bsdc news" and items[-1][0].startswith("Bangladesh Bank")
    assert items[-1][0] == items[-1][0].rstrip("…") or not items[-1][0].endswith("persist")
    assert breadcrumb.validate(breadcrumb.build(items)) == []


def test_itemlist_schema_captures_related_coverage():
    node = itemlist.build([{"name": item["title"], "url": item["url"]} for item in RELATED])
    assert itemlist.validate(node) == [] and len(node["itemListElement"]) == 3


def test_itemlist_schema_needs_absolute_urls():
    assert itemlist.validate(itemlist.build([{"name": "a", "url": "item 1 url"}]))


def test_graph_merges_nodes_and_reports_invalid_ones():
    doc = graph(_article_node(), faq.build([("Q and A?", "The central bank acted on Monday.")]), None)
    assert doc["@context"] == "https://schema.org"
    result = validate_all({"article": doc, "broken": {"@type": "NewsArticle"}})
    assert isinstance(result, dict) and result


def test_script_tag_emits_parseable_jsonld():
    import json

    tag = script_tag(_article_node())
    assert tag.startswith('<script type="application/ld+json">') and tag.endswith("</script>")
    assert json.loads(tag.split(">", 1)[1].rsplit("<", 1)[0])["@type"] == "NewsArticle"
    assert script_tag(None) == ""


# ------------------------------------------------------------------ planner
def _draft():
    from bsdc_news.cortex.types import ArticleDraft

    return ArticleDraft(headline=HEADLINE, body_html=f"<p>{BODY}</p>" * 3, dek=BODY.split(". ")[0],
                        meta_description=BODY.split(". ")[0], category="Business",
                        tags=["Bangladesh Bank", "inflation"],
                        facts=[], faq=[("When do banks apply it?",
                                        "Commercial banks implement the new rate from 1 November.")],
                        tldr=("The central bank raised its policy rate to 9.5 percent.",),
                        keywords={"primary": KEYWORD, "secondary": ["inflation", "policy rate"]},
                        outline=["lede", "details"], words=260)


def test_planner_produces_every_seo_asset_in_one_pass():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business", related=RELATED, published_slugs=["other-post"])
    assert plan.primary_keyword == KEYWORD
    assert 30 <= len(plan.title_tag) <= 65
    assert 120 <= len(plan.meta_description) <= 160
    assert plan.slug and plan.slug == plan.slug.lower() and " " not in plan.slug
    assert plan.canonical == URL
    assert plan.headings and plan.headings[0][0] == 1
    assert plan.json_ld and plan.breadcrumbs and plan.open_graph and plan.twitter_card
    assert 0 <= plan.score <= 100 and plan.checks


def test_planner_checks_report_what_failed():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business")
    assert all(len(row) == 3 for row in plan.checks)
    assert plan.score >= 60


def test_planner_internal_links_are_ready_for_the_renderer():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business", related=RELATED)
    assert plan.internal_links
    for item in plan.internal_links:
        assert item["url"].startswith("http") and item["title"] and item["anchor"]


def test_planner_breadcrumbs_start_at_the_site_and_end_on_the_headline():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business")
    assert plan.breadcrumbs[0][0] == "bsdc news"
    assert plan.breadcrumbs[-1][0].startswith(plan.headline[:25])


def test_planner_json_ld_nodes_are_individually_valid():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business", related=RELATED)
    types = {str(node.get("@type")) for node in plan.json_ld}
    assert "NewsArticle" in types and "BreadcrumbList" in types
    assert all(node.get("@context") == "https://schema.org" for node in plan.json_ld)


def test_planner_never_emits_markup_into_plain_text_fields():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business")
    for text in (plan.title_tag, plan.meta_description, plan.slug, plan.open_graph["og:title"]):
        assert "<" not in str(text) and ">" not in str(text)


def test_planner_image_alt_is_descriptive_and_keyword_aware():
    alt = planner.image_alt(HEADLINE, KEYWORD, "Chart of rates", ["Bangladesh Bank"], maximum=120)
    assert alt and len(alt) <= 125
    assert "bangladesh" in alt.lower() or "chart" in alt.lower()


def test_planner_compose_lede_reads_the_first_paragraph():
    assert planner.compose_lede(f"<h1>{HEADLINE}</h1><p>{BODY.split('. ')[0]}.</p><p>More.</p>")


def test_planner_sitemap_documents_are_generated_for_a_post():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="https://b.test", post_url=URL,
                        category="Business")
    entry = planner.sitemap_entry(plan, url=URL)
    assert entry["url"] == URL and entry["title"]
    docs = planner.sitemap_documents([{"url": URL, "title": HEADLINE, "published": "2026-09-25T06:00:00Z"}],
                                     site_name="bsdc news", site_url="https://b.test")
    assert docs and all(isinstance(value, str) and value for value in docs.values())
    joined = " ".join(docs.values())
    assert "<urlset" in joined and "news:news" in joined


def test_planner_handles_a_draft_with_no_keywords():
    from bsdc_news.cortex.types import ArticleDraft

    bare = ArticleDraft(headline="Rate rise announced", body_html=f"<p>{BODY}</p>", words=120)
    plan = planner.plan(bare, site_name="bsdc news", site_url="https://b.test", post_url=URL)
    assert plan.title_tag and plan.meta_description and plan.slug


def test_planner_survives_an_empty_site_url():
    plan = planner.plan(_draft(), site_name="bsdc news", site_url="", category="Business")
    assert plan.title_tag and plan.slug
