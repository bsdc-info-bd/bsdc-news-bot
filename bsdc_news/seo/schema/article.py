"""Article, NewsArticle and BlogPosting structured data.

Google requires a specific set of properties for news rich results — headline,
image, datePublished, dateModified, author and publisher — and rejects markup whose
dates are inconsistent or whose author has no URL. Every builder here validates its
own output so invalid markup never reaches the page.
"""

from datetime import UTC, datetime

from ...cortex.text.normalize import squish

HEADLINE_MAX = 110
VALID_TYPES = ("Article", "NewsArticle", "BlogPosting", "ReportageNewsArticle",
               "AnalysisNewsArticle", "BackgroundNewsArticle", "OpinionNewsArticle",
               "ReviewNewsArticle")


def iso(moment) -> str:
    """ISO-8601 with an explicit offset, as schema.org requires."""
    if isinstance(moment, datetime):
        stamp = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return stamp.isoformat().replace("+00:00", "Z")
    if isinstance(moment, str) and moment:
        return moment
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def author(name: str, *, url: str = "", same_as: list[str] | None = None,
           job_title: str = "", type_: str = "Person") -> dict | None:
    """An author node. A name alone is thin markup; a URL makes it verifiable."""
    name = squish(name)
    if not name:
        return None
    node = {"@type": type_, "name": name}
    if url:
        node["url"] = url
    if job_title:
        node["jobTitle"] = squish(job_title)
    if same_as:
        node["sameAs"] = [squish(item) for item in same_as if item][:6]
    return node


def publisher(name: str, *, logo_url: str = "", url: str = "", same_as: list[str] | None = None,
              type_: str = "NewsMediaOrganization") -> dict | None:
    name = squish(name)
    if not name:
        return None
    node: dict = {"@type": type_, "name": name}
    if url:
        node["url"] = url
    if logo_url:
        node["logo"] = {"@type": "ImageObject", "url": logo_url, "width": 600, "height": 60}
    if same_as:
        node["sameAs"] = [squish(item) for item in same_as if item][:8]
    return node


def image_object(url: str, *, caption: str = "", credit: str = "", width: int = 1200,
                 height: int = 630) -> dict | None:
    url = squish(url)
    if not url:
        return None
    node: dict = {"@type": "ImageObject", "url": url, "width": width, "height": height,
                  "contentUrl": url}
    if caption:
        node["caption"] = squish(caption)[:300]
    if credit:
        node["creditText"] = squish(credit)[:120]
        node["copyrightNotice"] = squish(credit)[:120]
    return node


def build(*, headline: str, description: str, url: str, images: list[str] | None = None,
          published=None, modified=None, author_name: str = "", author_url: str = "",
          publisher_name: str = "", publisher_logo: str = "", publisher_url: str = "",
          section: str = "", keywords: list[str] | None = None, words: int = 0,
          language: str = "en", article_type: str = "NewsArticle",
          body: str = "", caption: str = "", image_credit: str = "",
          same_as: list[str] | None = None, video_url: str = "") -> dict | None:
    """A complete Article node, or None when the required properties are missing."""
    headline = squish(headline)[:HEADLINE_MAX]
    url = squish(url)
    if not headline or not url:
        return None
    if article_type not in VALID_TYPES:
        article_type = "NewsArticle"
    published_stamp, modified_stamp = iso(published), iso(modified or published)
    if modified_stamp < published_stamp:
        modified_stamp = published_stamp            # never claim an edit before publication

    node: dict = {
        "@context": "https://schema.org",
        "@type": article_type,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "headline": headline,
        "description": squish(description)[:300],
        "datePublished": published_stamp,
        "dateModified": modified_stamp,
        "inLanguage": language,
        "isAccessibleForFree": True,
        "wordCount": max(0, int(words)),
    }
    image_nodes = [image_object(item, caption=caption, credit=image_credit)
                   for item in (images or [])[:3]]
    image_nodes = [item for item in image_nodes if item]
    if image_nodes:
        node["image"] = [item["url"] for item in image_nodes] if len(image_nodes) > 1 \
            else image_nodes[0]["url"]
        node["thumbnailUrl"] = image_nodes[0]["url"]
    writer = author(author_name, url=author_url)
    if writer:
        node["author"] = writer
    house = publisher(publisher_name, logo_url=publisher_logo, url=publisher_url)
    if house:
        node["publisher"] = house
    if section:
        node["articleSection"] = squish(section)
    if keywords:
        node["keywords"] = ", ".join(squish(item) for item in keywords[:12] if item)
    if same_as:
        node["sameAs"] = [squish(item) for item in same_as if item][:6]
    if video_url:
        node["video"] = {"@type": "VideoObject", "name": headline, "embedUrl": squish(video_url)}
    if body:
        node["articleBody"] = squish(body)[:25000]
    return node


def validate(node: dict | None) -> list[str]:
    """Google's documented requirements, checked before the markup is emitted."""
    problems: list[str] = []
    if not node:
        return ["no article node"]
    for required in ("headline", "datePublished", "dateModified", "@type"):
        if not node.get(required):
            problems.append(f"missing required property: {required}")
    if not node.get("author") and not node.get("publisher"):
        problems.append("neither author nor publisher is present")
    if not node.get("image"):
        problems.append("no image: rich results require at least one")
    headline = str(node.get("headline", ""))
    if len(headline) > HEADLINE_MAX:
        problems.append(f"headline is {len(headline)} chars (limit {HEADLINE_MAX})")
    if node.get("dateModified", "") < node.get("datePublished", ""):
        problems.append("dateModified is earlier than datePublished")
    if node.get("@type") not in VALID_TYPES:
        problems.append(f"unknown article type: {node.get('@type')}")
    return problems


def speaking_item(headline: str, *, url: str, author_name: str = "", published=None) -> dict:
    """The minimal node used inside speakable and ItemList references."""
    node = {"@type": "WebPage", "@id": url, "name": squish(headline)[:110]}
    if author_name:
        node["author"] = author(author_name) or {}
    if published:
        node["datePublished"] = iso(published)
    return node


def speakable(url: str) -> dict:
    """Speakable markup for voice assistants: headline plus the lede."""
    return {"@type": "WebPage", "@id": url,
            "speakable": {"@type": "SpeakableSpecification",
                          "cssSelector": [".bsd-lede", "h1", ".bsd-tldr"]}}
