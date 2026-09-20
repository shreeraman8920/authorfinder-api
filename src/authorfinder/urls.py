"""URL helpers: resolution, cleaning, author-page detection, social classification."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

TRACKING_PARAMS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref_src",
    "ref_url",
    "yclid",
    "_ga",
    "_gl",
    "cmpid",
    "ct",
    "mt",
    "cid",
    "ncid",
    "s_kwcid",
)

# Common path segments that identify an author/profile page.
AUTHOR_PATH_PATTERNS = re.compile(
    r"/(author|authors|byline|by-lines|bylineauthor|contributor|contributors|"
    r"reporter|reporters|writer|writers|journalist|journalists|profile|profiles|"
    r"staff|staffer|member|members|user|users|columnist|columnists|"
    r"editor|editors|correspondent|correspondents|blogger|bloggers|"
    r"bios|bio|presenter|presenters|"
    r"expert|experts|our-team|team|people)/",
    re.IGNORECASE,
)

AUTHOR_HOST_PREFIXES = (
    "author.",
    "authors.",
    "profiles.",
    "byline.",
    "staff.",
    "contributor.",
    "writers.",
    "reporters.",
)


def is_tracking_param(key: str) -> bool:
    key = key.lower()
    if key in TRACKING_PARAMS:
        return True
    return key.startswith("utm_") or key.startswith("hs_")


def clean_url(url: str) -> str:
    """Strip fragment and common tracking query parameters."""
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not is_tracking_param(k)]
    query = urlencode(pairs)
    return parsed._replace(fragment="", query=query).geturl()


def resolve_url(base_url: str, href: str) -> str | None:
    """Resolve a possibly-relative href against base_url.

    Returns a cleaned, absolute URL, or None for schemes we cannot crawl
    (mailto:, tel:, javascript:, data:, pure fragments).
    """
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    lowered = href.lower()
    if lowered.startswith(("javascript:", "data:", "mailto:", "tel:", "sms:")):
        return None
    url = urljoin(base_url, href)
    if not urlparse(url).scheme:
        return None
    return clean_url(url)


def same_domain(url: str, base_url: str) -> bool:
    """True if url lives on base_url's domain or a subdomain of it."""
    u = urlparse(url).netloc.lower()
    b = urlparse(base_url).netloc.lower()
    return u == b or u.endswith("." + b)


def looks_like_author_page(url: str) -> bool:
    """Heuristic: does this URL point at an author/profile page?"""
    parsed = urlparse(url)
    if AUTHOR_PATH_PATTERNS.search(parsed.path):
        return True
    host = parsed.netloc.lower()
    if host.startswith(AUTHOR_HOST_PREFIXES):
        return True
    return False


def looks_like_author_link(text: str, href: str) -> bool:
    """Heuristic: is this anchor (by text/href) pointing at an author profile?"""
    href = (href or "").lower()
    if AUTHOR_PATH_PATTERNS.search(href):
        return True
    t = (text or "").strip().lower()
    keywords = (
        "author",
        "byline",
        "profile",
        "contributor",
        "reporter",
        "journalist",
        "columnist",
        "about the author",
        "about this author",
        "view author",
        "visit author",
    )
    return any(k in t for k in keywords)


SOCIAL_HOSTS = {
    "twitter": ("twitter.com", "x.com"),
    "facebook": ("facebook.com", "fb.com"),
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "linkedin": ("linkedin.com", "lnkd.in"),
    "threads": ("threads.net",),
    "mastodon": ("mastodon.social", "mastodon.online", "mastodon.world",
                 "fosstodon.org", "hachyderm.io", "mas.to",
                 "social.coop", "mastodon.xyz", "mastodon.cloud"),
    "bluesky": ("bsky.app", "bsky.social"),
    "github": ("github.com",),
    "tiktok": ("tiktok.com",),
    "substack": ("substack.com",),
    "medium": ("medium.com",),
    "reddit": ("reddit.com",),
}

LINKEDIN_PROFILE_PATH = re.compile(r"^/(in|pub)/", re.IGNORECASE)
SUBSTACK_AUTHOR_PATH = re.compile(r"^/@[\w.-]+/?$", re.IGNORECASE)
MEDIUM_AUTHOR_PATH = re.compile(r"^/@[\w.-]+/?$", re.IGNORECASE)


def classify_social_link(url: str) -> str | None:
    """Return the platform key for a known social URL, or None."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        if LINKEDIN_PROFILE_PATH.match(parsed.path):
            return "linkedin"
        return None
    if host == "lnkd.in":
        return "linkedin"
    for key, hosts in SOCIAL_HOSTS.items():
        if any(h == host or host.endswith("." + h) for h in hosts):
            return key
    if host.endswith(".substack.com") and SUBSTACK_AUTHOR_PATH.match(parsed.path):
        return "substack"
    if host.endswith(".medium.com") and MEDIUM_AUTHOR_PATH.match(parsed.path):
        return "medium"
    if host.endswith(".bsky.app") or host.endswith(".bsky.social"):
        return "bluesky"
    return None


def normalize_article_url(url: str) -> str:
    """Ensure the article URL has an http(s) scheme."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        if not parsed.netloc:
            # bare host/path like "example.com/story" -> treat as host
            return "https://" + url
    return url
