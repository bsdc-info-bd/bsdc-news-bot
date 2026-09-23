from datetime import timedelta

from bsdc_news.dedupe import cluster, is_near_duplicate, title_fingerprint, title_similarity
from bsdc_news.feeds import FeedFetcher, FeedItem, parse_feed
from bsdc_news.filters import ItemFilter, looks_english
from bsdc_news.ranking import Ranker, diversify
from bsdc_news.settings import Feed
from bsdc_news.trends import trend_match
from bsdc_news.utils import utcnow

from .conftest import FakeHttp, feed_xml


def _item(title, host="a.com", hours=1, weight=1.0, category="Technology"):
    return FeedItem(title=title, url=f"https://{host}/{abs(hash(title))}", source=host, source_url=f"https://{host}",
                    category=category, published=utcnow() - timedelta(hours=hours), feed_weight=weight)


def test_parse_feed_extracts_items_images_and_dates():
    items = parse_feed(feed_xml(), Feed(url="https://example-tech.com/feed.xml", name="Example Tech"))
    assert len(items) == 4
    first = items[0]
    assert first.title.startswith("Nvidia unveils")
    assert first.image == "https://cdn.example-tech.com/rubin-ultra-feed.jpg"
    assert first.published is not None
    assert first.canonical == "https://example-tech.com/2026/09/22/nvidia-rubin-ultra"
    assert first.tags == ["AI"]


def test_feed_fetcher_isolates_failures():
    class Http(FakeHttp):
        def get(self, url, **kw):
            if "broken" in url:
                raise ConnectionError("boom")
            return super().get(url, **kw)

    fetcher = FeedFetcher(Http())
    results = fetcher.fetch_all([Feed(url="https://ok.com/feed.xml"), Feed(url="https://broken.com/feed.xml"),
                                 Feed(url="https://off.com/feed.xml", enabled=False)])
    assert len(results) == 2
    assert results[0].items and not results[0].error
    assert results[1].error.startswith("network error")


def test_filters_block_deals_old_and_non_english(settings):
    f = ItemFilter(settings)
    items = parse_feed(feed_xml(), Feed(url="https://example-tech.com/feed.xml"))
    decisions = {it.title[:20]: f.check(it) for it in items}
    assert decisions["Nvidia unveils Rubin"].ok
    assert not decisions["Samsung Promo Codes:"].ok
    assert not decisions["Old story about a sm"].ok
    assert "older" in decisions["Old story about a sm"].reason
    assert looks_english("Apple launches new iPhone") and not looks_english("বাংলাদেশে নতুন ফোন বাজারে")
    assert not f.check(_item("Today's Wordle hints and answers for September")).ok


def test_title_similarity_and_fingerprint():
    a = "Apple launches iPhone 18 with new camera system"
    b = "iPhone 18 with new camera system launched by Apple"
    assert title_fingerprint(a) == title_fingerprint("Apple launches iPhone 18 with new camera system!")
    assert title_similarity(a, b) > 0.6
    assert title_similarity(a, "Tesla recalls 2 million cars over autopilot") < 0.2
    assert is_near_duplicate(a, [b], 0.6) == b


def test_cluster_groups_same_story():
    items = [_item("OpenAI releases GPT-6 model with better reasoning", "a.com"),
             _item("OpenAI releases GPT-6 model, promising better reasoning", "b.com"),
             _item("Samsung Galaxy S27 leaks show new design", "c.com")]
    groups = cluster(items, 0.5)
    assert sorted(len(g) for g in groups) == [1, 2]


def test_ranker_prefers_fresh_hot_trending(settings):
    items = [_item("Old minor update to a niche app", hours=30),
             _item("Nvidia unveils new AI chip for data centers", "a.com", hours=1),
             _item("Nvidia unveils new AI chip for data centres", "b.com", hours=2)]
    ranked = Ranker(settings, trending_terms=["nvidia"]).rank(items)
    assert ranked[0].title.startswith("Nvidia")
    assert ranked[0].cluster_size == 2
    assert any("trending" in n for n in ranked[0].score_notes)
    assert len(ranked) == 2  # duplicates merged


def test_trend_match_requires_meaningful_overlap():
    assert trend_match("Nvidia stock jumps after keynote", ["nvidia"]) == "nvidia"
    assert trend_match("New AI chip announced", ["ai"]) == ""  # too short/generic
    assert trend_match("Jon Hamm stars in new series", ["jon hamm"]) == "jon hamm"


def test_diversify_caps_sources_and_categories():
    items = [_item(f"Story number {i} about chips", "same.com", category="AI") for i in range(5)]
    items += [_item("Other outlet story about phones", "other.com", category="Mobile")]
    picked = diversify(items, max_per_source=2, max_per_category=3, limit=4)
    assert sum(1 for p in picked if p.host == "same.com") == 2
    assert any(p.host == "other.com" for p in picked)
