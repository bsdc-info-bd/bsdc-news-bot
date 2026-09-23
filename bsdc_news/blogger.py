"""Blogger API v3 client (OAuth refresh token).

Adds on top of the original publisher: typed errors with fix hints,
blog-info discovery (site URL), paginated recent-post index for de-duplication,
live / draft / scheduled publishing, search-description (meta description)
support, post patching after insert and a dry-run implementation."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from .dedupe import title_fingerprint
from .errors import AuthError, PublishError
from .log import get_logger
from .utils import canonical_url, iso, utcnow

log = get_logger("blogger")

BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
TOKEN_URI = "https://oauth2.googleapis.com/token"
OAUTH_HELP = ("Re-create GOOGLE_REFRESH_TOKEN with the Blogger scope using scripts/get_refresh_token.py "
              "(the OAuth consent screen must be 'In production' — refresh tokens of apps in "
              "'Testing' expire after 7 days).")


@dataclass
class PublishedPost:
    post_id: str
    url: str
    status: str  # LIVE | DRAFT | SCHEDULED
    title: str


class BloggerClient:
    def __init__(self, blog_id: str, client_id: str, client_secret: str, refresh_token: str) -> None:
        self.blog_id = blog_id
        self._creds_args = (client_id, client_secret, refresh_token)
        self._service = None
        self.blog_info: dict = {}

    # ── connection ──
    def service(self):
        if self._service is None:
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            client_id, client_secret, refresh_token = self._creds_args
            creds = Credentials(None, refresh_token=refresh_token, client_id=client_id,
                                client_secret=client_secret, token_uri=TOKEN_URI, scopes=[BLOGGER_SCOPE])
            for attempt in range(3):
                try:
                    creds.refresh(Request())
                    break
                except RefreshError as exc:
                    text = str(exc)
                    if "invalid_grant" in text or "invalid_client" in text or "unauthorized_client" in text:
                        raise AuthError(f"Google OAuth refresh failed: {text[:200]}", hint=OAUTH_HELP) from exc
                    if attempt == 2:
                        raise AuthError(f"Google OAuth refresh failed: {text[:200]}", hint=OAUTH_HELP) from exc
                except Exception as exc:  # transport problems
                    if attempt == 2:
                        raise PublishError(f"Could not reach Google OAuth: {exc}", retryable=True) from exc
                time.sleep(2 * (attempt + 1))
            self._service = build("blogger", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _execute(self, request, what: str, retries: int = 3):
        from googleapiclient.errors import HttpError

        for attempt in range(retries):
            try:
                return request.execute(num_retries=1)
            except HttpError as exc:
                status = int(getattr(exc.resp, "status", 0) or 0)
                detail = exc._get_reason() if hasattr(exc, "_get_reason") else str(exc)
                if status in (401,):
                    raise AuthError(f"Blogger {what}: unauthorized ({detail})", hint=OAUTH_HELP) from exc
                if status == 403:
                    raise AuthError(f"Blogger {what}: forbidden ({detail})",
                                    hint="Make sure the Google account that created the refresh token is an "
                                         "admin/author of the blog and BLOG_ID is correct.") from exc
                if status == 404:
                    raise PublishError(f"Blogger {what}: not found ({detail}) — check BLOG_ID") from exc
                if status in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise PublishError(f"Blogger {what} failed: HTTP {status} {detail}",
                                   retryable=status in (429, 500, 502, 503, 504)) from exc
        raise PublishError(f"Blogger {what}: retries exhausted", retryable=True)

    # ── reads ──
    def get_blog(self) -> dict:
        if not self.blog_info:
            info = self._execute(self.service().blogs().get(blogId=self.blog_id, maxPosts=0), "blogs.get")
            self.blog_info = {"name": info.get("name", ""), "url": (info.get("url") or "").rstrip("/"),
                              "description": info.get("description", "")}
        return self.blog_info

    def recent_posts(self, limit: int = 150) -> list[dict]:
        posts: list[dict] = []
        token = None
        while len(posts) < limit:
            req = self.service().posts().list(
                blogId=self.blog_id, maxResults=min(50, limit - len(posts)), fetchBodies=False,
                status=["LIVE"], orderBy="PUBLISHED", pageToken=token,
                fields="nextPageToken,items(id,title,url,published,labels)")
            data = self._execute(req, "posts.list")
            posts.extend(data.get("items", []) or [])
            token = data.get("nextPageToken")
            if not token:
                break
        # Scheduled posts also count as "existing" for de-duplication
        try:
            data = self._execute(self.service().posts().list(
                blogId=self.blog_id, maxResults=20, fetchBodies=False, status=["SCHEDULED"],
                view="ADMIN", fields="items(id,title,url,published,labels)"), "posts.list(scheduled)", retries=1)
            posts.extend(data.get("items", []) or [])
        except Exception:
            pass
        return posts

    def recent_source_links(self, limit: int = 60) -> list[tuple[str, str]]:
        """(source_url, post_title) for recent posts — used to rebuild lost state so an
        AI-retitled story is never published twice."""
        data = self._execute(self.service().posts().list(
            blogId=self.blog_id, maxResults=min(limit, 100), fetchBodies=True, status=["LIVE"],
            fields="items(title,content)"), "posts.list(bodies)", retries=2)
        return extract_source_links(data.get("items", []) or [])

    # ── writes ──
    def insert(self, title: str, content: str, labels: list[str], *, draft: bool = False,
               publish_at: datetime | None = None, search_description: str = "") -> PublishedPost:
        # NOTE: the Blogger API cannot set a post's "search description"; the renderer puts the
        # meta description first in the post instead (Blogger uses it as the snippet).
        body = {"kind": "blogger#post", "title": title, "content": content, "labels": labels}
        is_draft = draft or publish_at is not None
        post = self._execute(self.service().posts().insert(blogId=self.blog_id, body=body, isDraft=is_draft,
                                                           fetchBody=False, fetchImages=False), "posts.insert")
        status = "DRAFT" if draft else "LIVE"
        if publish_at is not None and not draft:
            post = self._execute(self.service().posts().publish(
                blogId=self.blog_id, postId=post["id"], publishDate=iso(publish_at)), "posts.publish")
            status = "SCHEDULED"
        return PublishedPost(post_id=post.get("id", ""), url=post.get("url", ""), status=post.get("status", status),
                             title=post.get("title", title))

    def update_content(self, post_id: str, content: str) -> None:
        self._execute(self.service().posts().patch(blogId=self.blog_id, postId=post_id,
                                                   body={"content": content}, fetchBody=False),
                      "posts.patch", retries=2)


_SOURCE_LINK_RES = [
    re.compile(r'<a[^>]*class="bsdc-source"[^>]*href="([^"]+)"', re.I),
    re.compile(r'<a[^>]*href="([^"]+)"[^>]*class="bsdc-source"', re.I),
    re.compile(r'<a[^>]*href="([^"]+)"[^>]*>\s*(?:Original Article|Read the original article)', re.I),  # v5 posts
]


def extract_source_links(posts: list[dict]) -> list[tuple[str, str]]:
    out = []
    for post in posts:
        content = post.get("content") or ""
        for regex in _SOURCE_LINK_RES:
            match = regex.search(content)
            if match:
                out.append((html.unescape(match.group(1)), post.get("title", "")))
                break
    return out


class DryRunBlogger:
    """Same interface as BloggerClient but never writes (used by --dry-run).

    When real credentials are available it *reads* the real blog, so a dry run
    de-duplicates exactly like a live run would."""

    def __init__(self, site_url: str = "https://example.blogspot.com", reader: BloggerClient | None = None) -> None:
        self.site_url = site_url.rstrip("/") or "https://example.blogspot.com"
        self.reader = reader
        self.inserted: list[dict] = []
        self.blog_info = {"name": "bsdc news (dry run)", "url": self.site_url}

    def _read(self, method: str, default, *args):
        if self.reader is None:
            return default
        try:
            return getattr(self.reader, method)(*args)
        except Exception as exc:  # read problems must not break a dry run
            log.warning("Dry run: could not read the real blog (%s) — continuing without it", exc)
            self.reader = None
            return default

    def get_blog(self) -> dict:
        info = self._read("get_blog", None)
        if info:
            self.blog_info = {**info, "name": f"{info.get('name', 'blog')} (dry run)"}
            self.site_url = info.get("url") or self.site_url
        return self.blog_info

    def recent_posts(self, limit: int = 150) -> list[dict]:
        return self._read("recent_posts", [], limit)

    def recent_source_links(self, limit: int = 60) -> list[tuple[str, str]]:
        return self._read("recent_source_links", [], limit)

    def insert(self, title, content, labels, *, draft=False, publish_at=None, search_description=""):
        from .utils import slugify

        now = utcnow()
        url = f"{self.site_url}/{now:%Y/%m}/{slugify(title, 60)}.html"
        pid = str(1000 + len(self.inserted))
        self.inserted.append({"id": pid, "title": title, "content": content, "labels": labels, "url": url,
                              "draft": draft, "publish_at": iso(publish_at) if publish_at else None,
                              "search_description": search_description})
        return PublishedPost(post_id=pid, url=url, status="DRAFT" if draft else "LIVE", title=title)

    def update_content(self, post_id, content):
        for post in self.inserted:
            if post["id"] == post_id:
                post["content"] = content


class ExistingIndex:
    """Fast lookups of what the blog already has (titles, fingerprints, source links)."""

    def __init__(self, posts: list[dict]) -> None:
        self.posts = posts
        self.titles = {(p.get("title") or "").strip().lower() for p in posts}
        self.fingerprints = {title_fingerprint(p.get("title") or "") for p in posts}
        self.urls = [p.get("url") for p in posts if p.get("url")]
        self.canonical = {canonical_url(u) for u in self.urls}

    def recent(self, n: int = 8) -> list[dict]:
        return [{"title": p.get("title", ""), "url": p.get("url", "")} for p in self.posts[:n]]


def schedule_times(count: int, stagger_minutes: int, start: datetime | None = None) -> list[datetime | None]:
    if stagger_minutes <= 0:
        return [None] * count
    start = start or utcnow()
    return [None if i == 0 else start + timedelta(minutes=stagger_minutes * i) for i in range(count)]
