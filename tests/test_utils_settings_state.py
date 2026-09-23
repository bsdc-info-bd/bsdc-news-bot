from datetime import datetime, timedelta

import pytest

from bsdc_news.errors import ConfigError
from bsdc_news.settings import load_settings, sanitize_secret
from bsdc_news.state import State
from bsdc_news.utils import (
    UTC,
    canonical_url,
    esc,
    in_time_window,
    json_for_html,
    next_midnight,
    slugify,
    truncate,
    word_count,
)


def test_canonical_url_strips_tracking_and_www():
    a = canonical_url("https://www.Example.com/story/?utm_source=rss&utm_medium=feed&id=5#top")
    b = canonical_url("http://example.com/story?id=5")
    assert a == b == "https://example.com/story?id=5"
    assert canonical_url("https://example.com/news/amp") == "https://example.com/news"


def test_text_helpers():
    assert word_count("Hello, world — it's 2026!") == 4
    assert truncate("one two three four five", 12) == "one two…"
    assert slugify("Nvidia’s Rubin: 2x faster!") == "nvidias-rubin-2x-faster"
    assert esc('<b a="x">') == "&lt;b a=&quot;x&quot;&gt;"
    assert "</script" not in json_for_html({"x": "</script><script>alert(1)</script>"})


def test_time_window_wraps_midnight():
    tz = "UTC"
    at = datetime(2026, 9, 23, 2, 30, tzinfo=UTC)
    assert in_time_window("01:00-06:00", tz, at)
    assert in_time_window("22:00-03:00", tz, at)
    assert not in_time_window("07:00-12:00", tz, at)
    assert not in_time_window("garbage", tz, at)


def test_next_midnight_pacific_is_in_future():
    now = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)
    nm = next_midnight("America/Los_Angeles", now)
    assert nm > now and (nm - now) <= timedelta(hours=24)


def test_sanitize_secret_only_strips_wrappers():
    assert sanitize_secret('  "AQ.abc"  ') == "AQ.abc"
    assert sanitize_secret("['abc']") == "abc"
    assert sanitize_secret("ab'c") == "ab'c"  # inner characters are preserved (v5 bug)


def test_settings_env_overrides_and_legacy_secret_names():
    s = load_settings(env={"BLOG_ID": "123456", "GEMINI_API_KEY": "AQ.key-value", "BSDC_MAX_POSTS": "7",
                           "BSDC_AI_PROVIDERS": "groq, gemini", "BSDC_AI_ENABLED": "false"})
    assert s.secret("blog_id") == "123456"
    assert s.secret("gemini_api_key") == "AQ.key-value"
    assert s.get("publishing.max_posts_per_run") == 7
    assert s.get("ai.providers") == ["groq", "gemini"]
    assert s.get("ai.enabled") is False
    assert s.feeds, "feeds.yaml should load"


def test_validate_reports_missing_secrets_clearly():
    s = load_settings(env={})
    with pytest.raises(ConfigError) as exc:
        s.validate(require_publish=True)
    assert "BLOG_ID" in str(exc.value) and "GOOGLE_REFRESH_TOKEN" in str(exc.value)
    # dry runs do not need secrets
    s.dry_run = True
    s.validate(require_publish=True)


def test_validate_rejects_non_numeric_blog_id():
    s = load_settings(env={"BLOG_ID": "my-blog", "GOOGLE_CLIENT_ID": "a", "GOOGLE_CLIENT_SECRET": "b",
                           "GOOGLE_REFRESH_TOKEN": "c"})
    with pytest.raises(ConfigError, match="numeric"):
        s.validate()


def test_state_roundtrip_and_backoff(tmp_path):
    st = State.load(tmp_path / "s.json")
    url = "https://example.com/a?utm_source=x"
    st.mark_published(url, {"title": "A"}, fingerprint="a b")
    assert st.is_published("https://www.example.com/a")
    st.record_failure("https://example.com/b", "B", "timeout")
    assert st.should_skip_failed("https://example.com/b", retry_hours=12, max_attempts=3)
    assert not st.should_skip_failed("https://example.com/b", retry_hours=0, max_attempts=3)
    st.record_failure("https://example.com/c", "C", "404", permanent=True)
    assert st.should_skip_failed("https://example.com/c", retry_hours=0, max_attempts=3)
    st.quota_add("posts", 2)
    assert st.quota_used("posts") == 2
    st.save()
    again = State.load(tmp_path / "s.json")
    assert again.is_published(url) and again.quota_used("posts") == 2 and again.title_seen("a b")


def test_state_survives_corrupt_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    st = State.load(p)
    assert st.data["published"] == {}
    assert (tmp_path / "state.corrupt.json").exists()


def test_state_consecutive_failures_and_indexing_queue(tmp_path):
    st = State.load(tmp_path / "s.json")
    assert st.record_run(False) == 1 and st.record_run(False) == 2 and st.record_run(True) == 0
    st.queue_for_indexing(["u1", "u2", "u3"])
    assert st.pop_indexing(2) == ["u1", "u2"]
    st.requeue_indexing(["u2"])
    assert st.data["indexing_queue"] == ["u2", "u3"]


def test_provider_circuit_breaker_resets_on_key_rotation(tmp_path):
    from datetime import timedelta as td

    from bsdc_news.utils import utcnow as now

    st = State.load(tmp_path / "s.json")
    st.disable_provider("gemini", now() + td(hours=6), "401 AIzaSECRETKEYVALUE", key_fp="old")
    assert st.provider_disabled("gemini", "old")
    assert not st.provider_disabled("gemini", "new")  # user rotated the key → retry at once


def test_paced_allowance_spreads_posts_over_the_day():
    from bsdc_news.utils import paced_allowance

    def at(h, m=0):
        return datetime(2026, 9, 23, h, m, tzinfo=UTC)

    assert paced_allowance(24, "UTC", at(0, 0)) == 2      # small lead after midnight
    assert paced_allowance(24, "UTC", at(12, 0)) == 14
    assert paced_allowance(24, "UTC", at(23, 30)) == 24
    assert paced_allowance(5, "UTC", at(0, 5)) == 1
    # timezone aware: 18:00 UTC is 00:00 in Dhaka (UTC+6)
    assert paced_allowance(24, "Asia/Dhaka", at(18, 0)) == 2


def test_state_keeps_meta_and_run_flags_across_reload(tmp_path):
    st = State.load(tmp_path / "s.json")
    st.data["meta"]["rebuilt_from_blog"] = "2026-09-23T00:00:00Z"
    st.data["runs"]["last_ai_auth_alert"] = "2026-09-23T00:00:00Z"
    st.save()
    again = State.load(tmp_path / "s.json")
    assert again.data["meta"]["rebuilt_from_blog"] and again.data["runs"]["last_ai_auth_alert"]
