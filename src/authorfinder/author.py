"""Author detection on the article page."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .extract import extract_json_ld, iter_all_nodes
from .urls import looks_like_author_page, resolve_url, same_domain

log = logging.getLogger(__name__)

BYLINE_SELECTORS = (
    "a[rel~='author']",
    "a[rel='author']",
    ".byline a",
    ".byline__name a",
    ".byline-name a",
    ".author a",
    ".author__name a",
    ".author-name a",
    ".author-name",
    ".contributor a",
    ".contributor__name a",
    ".contributor-name a",
    "[class*=byline] a",
    "[class*=author] a",
)

AUTHOR_META_KEYS = {
    "author",
    "byl",
    "byline",
    "article:author",
    "parsely-author",
    "sailthru.author",
    "author_name",
    "dc.creator",
    "citation_author",
    "dcterms.creator",
}

# Words that appear as author-box anchor labels but are not person names.
_NON_NAME_WORDS = {
    "twitter",
    "x",
    "facebook",
    "instagram",
    "linkedin",
    "youtube",
    "email",
    "contact",
    "about",
    "about the author",
    "bio",
    "biography",
    "stories",
    "articles",
    "archives",
    "follow",
    "share",
    "view all",
    "see all",
    "read more",
    "home",
    "search",
    "more",
    "all stories",
    "website",
    "threads",
    "bluesky",
    "mastodon",
    "pharma",
    "biotech",
    "medtech",
    "people",
    "policy",
    "patients",
    "regulation",
    "business",
    "technology",
    "opinion",
    "analysis",
    "news",
    "latest",
    "topic",
    "topics",
    "channels",
}

_PERSON_NAME_RE = re.compile(r"[\w\u00C0-\u024F''.\- ]+$")


@dataclass
class AuthorCandidate:
    name: str | None = None
    profile_url: str | None = None


def _is_plausible_person_name(text: str | None) -> bool:
    if not text:
        return False
    text = text.strip()
    if not (1 <= len(text) <= 80):
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    if not _PERSON_NAME_RE.match(text):
        return False
    lower = text.lower()
    if lower in _NON_NAME_WORDS or lower.split()[0] in _NON_NAME_WORDS:
        return False
    if "http" in lower or "@" in text:
        return False
    if text.count(" ") > 5:
        return False
    return True


def detect_authors(soup: BeautifulSoup, article_url: str) -> list[AuthorCandidate]:
    """Find every author mentioned on the article page (name and/or profile URL)."""
    candidates: list[AuthorCandidate] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str | None, url: str | None) -> None:
        if url:
            url = resolve_url(article_url, url)
        name = (name or "").strip() or None
        if url is None and name is None:
            return
        key = ((name or "").lower(), url or "")
        if key in seen:
            return
        seen.add(key)
        candidates.append(AuthorCandidate(name=name, profile_url=url))

    _detect_from_json_ld(soup, article_url, add)
    _detect_from_meta(soup, article_url, add)
    _detect_from_byline_links(soup, article_url, add)
    _detect_from_author_path_links(soup, article_url, add)
    _detect_from_microdata(soup, article_url, add)
    _detect_from_title(soup, add)

    return candidates


def _detect_from_json_ld(soup: BeautifulSoup, article_url: str, add) -> None:
    blocks = extract_json_ld(soup)
    for block in blocks:
        for node in iter_all_nodes(block):
            if not isinstance(node, dict):
                continue
            # NewsArticle.author can be a plain string.
            author = node.get("author")
            if isinstance(author, str) and _is_plausible_person_name(author):
                add(author, None)
            # Person / Author nodes.
            t = node.get("@type")
            types = t if isinstance(t, list) else ([t] if t else [])
            if not any("Person" in str(x) or "Author" in str(x) for x in types):
                continue
            name = node.get("name")
            url = node.get("url")
            if isinstance(name, str):
                name = name.strip() or None
            if isinstance(url, str):
                if same_domain(url, article_url):
                    add(name, url)
                else:
                    # External author.url (e.g. a social profile) is not the
                    # site's author page; keep only the name.
                    add(name, None)
                continue
            # No explicit url: prefer a same-site profile URL among sameAs.
            for same in node.get("sameAs") or []:
                if not isinstance(same, str):
                    continue
                if same_domain(same, article_url):
                    add(name, same)
            add(name, None)


def _detect_from_meta(soup: BeautifulSoup, article_url: str, add) -> None:
    for m in soup.find_all("meta"):
        content = (m.get("content") or "").strip()
        if not content:
            continue
        key = (m.get("name") or m.get("property") or "").lower()
        if key not in AUTHOR_META_KEYS:
            continue
        if content.lower().startswith("http"):
            # URL form (e.g. article:author). Only a URL on the same website
            # can serve as the author profile page; external URLs (frequently
            # the publisher's Facebook page) are ignored.
            if same_domain(content, article_url):
                add(None, content)
            continue
        for part in re.split(r"[;,]|(?:\s+and\s+)", content):
            part = part.strip()
            if _is_plausible_person_name(part):
                add(part, None)


def _detect_from_byline_links(soup: BeautifulSoup, article_url: str, add) -> None:
    # Collect the article's own URL (after resolution) to skip self-links.
    resolved_article = resolve_url(article_url, article_url) or article_url
    for sel in BYLINE_SELECTORS:
        for a in soup.select(sel):
            href = a.get("href")
            if not href:
                text = a.get_text(" ", strip=True)
                if _is_plausible_person_name(text):
                    add(text, None)
                continue
            url = resolve_url(article_url, href)
            if url and same_domain(url, article_url) and url == resolved_article:
                continue
            text = a.get_text(" ", strip=True)
            name = text if _is_plausible_person_name(text) else None
            if url and not same_domain(url, article_url):
                # External links (e.g. an author's Twitter) are not the
                # site's author profile page; keep only the name.
                add(name, None)
            else:
                add(name, url)


def _detect_from_author_path_links(soup: BeautifulSoup, article_url: str, add) -> None:
    for a in soup.find_all("a", href=True):
        href = a["href"]
        url = resolve_url(article_url, href)
        if not url or not same_domain(url, article_url):
            continue
        if url == (resolve_url(article_url, article_url) or article_url):
            continue
        if looks_like_author_page(url):
            text = a.get_text(" ", strip=True)
            name = text if _is_plausible_person_name(text) else None
            add(name, url)


def _detect_from_microdata(soup: BeautifulSoup, article_url: str, add) -> None:
    """Detect authors from Schema.org microdata (itemscope/itemprop)."""
    for el in soup.find_all(attrs={"itemprop": "author"}):
        name = None
        url = None
        if el.name == "a":
            url = el.get("href")
            name = el.get_text(" ", strip=True)
        elif el.has_attr("itemscope"):
            name_el = el.find(attrs={"itemprop": "name"})
            if name_el:
                name = name_el.get_text(" ", strip=True)
            url_el = el.find(attrs={"itemprop": "url"})
            if url_el:
                url = url_el.get("href") or url_el.get_text(" ", strip=True)
        else:
            name = el.get_text(" ", strip=True)
        if name and _is_plausible_person_name(name):
            add(name, resolve_url(article_url, url) if url else None)
    for el in soup.find_all(attrs={"itemprop": "author"}):
        if el.has_attr("itemscope"):
            for link in el.find_all("a", href=True):
                href = link.get("href")
                resolved = resolve_url(article_url, href)
                if resolved and same_domain(resolved, article_url):
                    if looks_like_author_page(resolved):
                        add(None, resolved)


def _detect_from_title(soup: BeautifulSoup, add) -> None:
    title_tag = soup.find("title")
    if title_tag is None:
        return
    title = title_tag.get_text(" ", strip=True)
    # Common patterns: "Headline - By John Doe | Site" or "By John Doe".
    m = re.search(r"(?i)\bBy\s+([A-Z][\w'’.\- ]{1,70}?)(?:\s*[|\-–—]\s|$)", title)
    if m:
        name = m.group(1).strip().rstrip("|–—")
        if _is_plausible_person_name(name):
            add(name, None)


def choose_author(candidates: list[AuthorCandidate], article_url: str) -> AuthorCandidate | None:
    """Pick the strongest author candidate (name + same-site profile page wins)."""
    best: AuthorCandidate | None = None
    best_score = -1
    for c in candidates:
        score = 0
        if c.name:
            score += 1
        if c.profile_url:
            score += 1
            if same_domain(c.profile_url, article_url):
                score += 1
            if looks_like_author_page(c.profile_url):
                score += 1
        if score > best_score:
            best_score = score
            best = c
    return best


def choose_multiple_authors(candidates: list[AuthorCandidate], article_url: str) -> list[AuthorCandidate]:
    """Pick multiple distinct author candidates (for multi-author articles).

    Returns candidates that have at least a name, deduplicated by name,
    limited to a reasonable count.
    """
    MAX_AUTHORS = 10
    seen_names: set[str] = set()
    result: list[AuthorCandidate] = []
    for c in candidates:
        if not c.name:
            continue
        normalized = c.name.lower().strip()
        if normalized in seen_names:
            continue
        seen_names.add(normalized)
        result.append(c)
        if len(result) >= MAX_AUTHORS:
            break
    return result