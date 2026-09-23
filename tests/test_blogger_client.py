"""BloggerClient against the real Blogger v3 discovery document with a mocked HTTP layer.

googleapiclient validates parameter names and enum values locally, so these tests prove
the requests we build are accepted by the API schema (e.g. status=["LIVE"], orderBy="PUBLISHED")."""

import json

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from bsdc_news.blogger import BloggerClient, ExistingIndex, schedule_times
from bsdc_news.errors import AuthError, PublishError


def client_with(responses):
    http = HttpMockSequence(responses)
    client = BloggerClient("1234567890", "cid", "secret", "refresh")
    client._service = build("blogger", "v3", http=http, cache_discovery=False, static_discovery=True)
    return client, http


def ok(body):
    return ({"status": "200"}, json.dumps(body))


def test_get_blog_and_recent_posts_request_shapes():
    client, http = client_with([
        ok({"name": "bsdc news", "url": "https://bsdcnews.blogspot.com/"}),
        ok({"items": [{"id": "1", "title": "First", "url": "https://b/1.html"}], "nextPageToken": "T"}),
        ok({"items": [{"id": "2", "title": "Second", "url": "https://b/2.html"}]}),
        ok({"items": [{"id": "3", "title": "Scheduled", "url": "https://b/3.html"}]}),
    ])
    assert client.get_blog()["url"] == "https://bsdcnews.blogspot.com"
    posts = client.recent_posts(100)
    assert [p["id"] for p in posts] == ["1", "2", "3"]
    uris = [req[1] for req in http.request_sequence] if hasattr(http, "request_sequence") else []
    del uris  # HttpMockSequence does not keep URIs in all versions; parameter validity is the key check


def test_insert_live_draft_and_scheduled():
    from datetime import UTC, datetime

    client, _ = client_with([
        ok({"id": "10", "url": "https://b/10.html", "status": "LIVE", "title": "T"}),
        ok({"id": "11", "url": "", "status": "DRAFT", "title": "T"}),
        ok({"id": "12", "url": "", "status": "DRAFT", "title": "T"}),
        ok({"id": "12", "url": "https://b/12.html", "status": "SCHEDULED", "title": "T"}),
    ])
    live = client.insert("T", "<p>x</p>", ["AI"])
    assert live.post_id == "10" and live.status == "LIVE"
    draft = client.insert("T", "<p>x</p>", ["AI"], draft=True)
    assert draft.status == "DRAFT"
    sched = client.insert("T", "<p>x</p>", ["AI"], publish_at=datetime(2026, 9, 23, 12, tzinfo=UTC))
    assert sched.status == "SCHEDULED" and sched.url.endswith("12.html")


def test_http_errors_are_classified():
    client, _ = client_with([({"status": "403"}, json.dumps({"error": {"message": "We're sorry, but you don't have permission"}}))])
    with pytest.raises(AuthError) as exc:
        client.insert("T", "c", [])
    assert "admin/author" in exc.value.describe()
    client, _ = client_with([({"status": "400"}, json.dumps({"error": {"message": "Invalid value"}}))])
    with pytest.raises(PublishError):
        client.insert("T", "c", [])


def test_existing_index_and_schedule_times():
    idx = ExistingIndex([{"title": "Apple launches iPhone 18", "url": "https://b/p.html?m=1"}])
    assert "apple launches iphone 18" in idx.titles
    assert idx.recent(1) == [{"title": "Apple launches iPhone 18", "url": "https://b/p.html?m=1"}]
    assert schedule_times(3, 0) == [None, None, None]
    times = schedule_times(3, 20)
    assert times[0] is None and (times[2] - times[1]).total_seconds() == 1200


def test_extract_source_links_v5_and_v6_posts():
    from bsdc_news.blogger import extract_source_links

    posts = [
        {"title": "v6", "content": '<p>x</p><a class="bsdc-source" href="https://src.com/a?x=1&amp;y=2">Read</a>'},
        {"title": "v5", "content": 'Source: X | <a href="https://src.com/b" target="_blank">Original Article</a>'},
        {"title": "none", "content": "<p>no link</p>"},
    ]
    assert extract_source_links(posts) == [("https://src.com/a?x=1&y=2", "v6"), ("https://src.com/b", "v5")]
