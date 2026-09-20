"""Information extraction from HTML: emails, social links, JSON-LD, bio, etc."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .urls import classify_social_link, resolve_url

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# "name [at] domain [dot] com" style obfuscation (also (at)/(dot), name(at)domain(dot)com)
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+-]+)\s*[\[]?[\(]?\s*at\s*[\)]?[\]]?\s*"
    r"([A-Za-z0-9.-]+)\s*[\[]?[\(]?\s*dot\s*[\)]?[\]]?\s*([A-Za-z]{2,})\b",
    re.IGNORECASE,
)

_PLACEHOLDER_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "yourdomain.com",
    "domain.com",
    "email.com",
    "sentry.io",
    "wixpress.com",
    "site.com",
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".pdf")

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub(" ", text)

BIO_SELECTORS = (
    ".author-bio",
    ".author__bio",
    ".bio",
    ".author-description",
    ".author__description",
    ".author-about",
    ".author__about",
    ".about-the-author",
    ".author-summary",
    ".profile-description",
    ".author-intro",
    ".author__intro",
    ".about-author",
    ".author-blurb",
    ".contributor-bio",
    ".byline-bio",
    ".author .description",
)

JOB_TITLE_SELECTORS = (
    ".author-title",
    ".author__title",
    ".job-title",
    ".jobtitle",
    ".author-role",
    ".author__role",
    ".author-position",
    ".author__position",
    ".role",
    ".position",
    ".author .role",
)

LOCATION_SELECTORS = (
    ".author-location",
    ".author__location",
    ".author-city",
    ".author-locality",
    ".author-location",
    ".author .location",
    ".location",
)


def _is_plausible_email(addr: str) -> bool:
    addr = addr.strip().rstrip(".")
    if addr.endswith(_IMAGE_SUFFIXES):
        return False
    lower = addr.lower()
    if any(lower.endswith("@" + d) for d in _PLACEHOLDER_DOMAINS):
        return False
    # catches retina-image artifacts like "logo@2x" (already filtered) and "name@example.com/path"
    if "/" in addr:
        return False
    return True


# Shared mailboxes that must not be presented as the author's own address.
_GENERIC_LOCAL_PARTS = (
    "info",
    "contact",
    "editor",
    "editorial",
    "newsroom",
    "news",
    "press",
    "tips",
    "admin",
    "webmaster",
    "support",
    "hello",
    "desk",
    "letters",
    "subscriptions",
    "subscribers",
    "advertising",
    "sales",
)


def _name_tokens(name: str | None) -> list[str]:
    if not name:
        return []
    return [t for t in re.split(r"[^\w]+", name.lower()) if len(t) > 2]


def _rank_emails(emails: list[str], name: str | None, page_url: str) -> list[str]:
    """Order candidate emails by how likely they belong to the author.

    Prefers addresses whose local part contains the author's name and whose
    domain matches the site, and demotes obvious shared mailboxes (info@,
    tips@). Ordering is stable, so ties keep their discovery order.
    """
    tokens = _name_tokens(name)
    host = urlparse(page_url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    root = ".".join(host.split(".")[-2:]) if host.count(".") >= 1 else host

    def score(addr: str) -> int:
        local, _, domain = addr.lower().partition("@")
        value = 0
        if tokens and any(token in local for token in tokens):
            value += 3
        if root and domain.endswith(root):
            value += 1
        if any(local.startswith(g) or local == g for g in _GENERIC_LOCAL_PARTS):
            value -= 3
        return value

    return sorted(emails, key=score, reverse=True)


def _decode_cf_email(encoded: str) -> str:
    """Decode a Cloudflare data-cfemail hex string (single-byte XOR obfuscation)."""
    if len(encoded) < 2:
        return ""
    key = int(encoded[:2], 16)
    chars = []
    for i in range(2, len(encoded), 2):
        chars.append(chr(int(encoded[i : i + 2], 16) ^ key))
    return "".join(chars)


def _visible_text(scope) -> str:
    """Text of a region, excluding script/style/noscript content."""
    parts = []
    for node in scope.find_all(string=True, recursive=True):
        parent = node.parent
        if parent is not None and parent.name in ("script", "style", "noscript"):
            continue
        parts.append(str(node))
    return " ".join(parts)


def extract_emails(soup: BeautifulSoup, container=None) -> list[str]:
    """Return deduplicated email addresses that belong to the author.

    Sources: Person JSON-LD `email`, plus `mailto:` links and email-like text
    inside the author region. Emails that belong to the site (an Organization's
    contact address, a newsletter signup box, a footer "Contact us" link) are
    not attributed to the author.
    """
    found: set[str] = set()

    for person in iter_ld_persons(extract_json_ld(soup)):
        addr = person.get("email")
        if isinstance(addr, str):
            addr = addr.strip()
            if _is_plausible_email(addr):
                found.add(addr)

    if container is not None:
        scopes = container if isinstance(container, list) else [container]
    else:
        scopes = _author_scope(soup) or _main_scope(soup) or [soup]

    for scope in scopes:
        for a in scope.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                addr = href[7:].split("?")[0].strip()
                if _is_plausible_email(addr):
                    found.add(addr)
        text = _visible_text(scope)
        for m in EMAIL_RE.finditer(text):
            addr = m.group(0).strip(".")
            if _is_plausible_email(addr):
                found.add(addr)
        for m in OBFUSCATED_EMAIL_RE.finditer(text):
            local, domain, tld = m.groups()
            addr = f"{local}@{domain}.{tld}"
            if _is_plausible_email(addr):
                found.add(addr)
        for el in scope.find_all(attrs={"data-cfemail": True}):
            addr = _decode_cf_email(el["data-cfemail"])
            if _is_plausible_email(addr):
                found.add(addr)
        for el in scope.find_all(True):
            for attr_name, attr_val in el.attrs.items():
                if attr_name.startswith("data-") and attr_name != "data-cfemail" and isinstance(attr_val, str):
                    for m in EMAIL_RE.finditer(attr_val):
                        addr = m.group(0).strip(".")
                        if _is_plausible_email(addr):
                            found.add(addr)
    return sorted(found)


AUTHOR_SCOPE_SELECTORS = (
    ".author",
    ".byline",
    ".profile",
    ".person",
    ".staff",
    ".staff-member",
    ".contributor",
    ".reporter",
    ".writer",
    "[class*=author]",
    "[class*=byline]",
    "[class*=contributor]",
    "[class*=profile]",
    "[class*=staff]",
    "[class*=person]",
)


def _author_scope(soup: BeautifulSoup) -> list:
    """Regions of an author page that hold the author's own links.

    Elements that match only because they wrap the whole page (e.g. WordPress
    puts author classes on <body>) are excluded so the scan stays targeted.
    """
    scopes: list = []
    for sel in AUTHOR_SCOPE_SELECTORS:
        scopes.extend(soup.select(sel))
    targeted = []
    for el in scopes:
        if el.name in ("html", "body"):
            continue
        if el.find("header") is not None or el.find("footer") is not None:
            continue
        targeted.append(el)
    return targeted


def _main_scope(soup: BeautifulSoup) -> list:
    """Whole-content regions (used as a fallback when no author container exists)."""
    scopes: list = []
    for sel in ("main", "article"):
        scopes.extend(soup.select(sel))
    return scopes


def _collect_social_from_anchors(soup: BeautifulSoup, base_url: str, scopes: list | None) -> dict:
    """Scan anchor hrefs inside the given regions for social links (deduplicated)."""
    links: dict[str, str] = {}
    seen: set[int] = set()
    for scope in (scopes if scopes is not None else [soup]):
        for a in scope.find_all("a", href=True):
            if id(a) in seen:
                continue
            seen.add(id(a))
            if _is_prose_citation(a):
                continue
            url = resolve_url(base_url, a["href"])
            if not url:
                continue
            platform = classify_social_link(url)
            if platform and platform not in links:
                links[platform] = url
    return links


def _collect_social_from_sameas(soup: BeautifulSoup, base_url: str) -> dict:
    """Social links declared for the author in JSON-LD Person.sameAs."""
    links: dict[str, str] = {}
    for person in iter_ld_persons(extract_json_ld(soup)):
        for same in person.get("sameAs") or []:
            if not isinstance(same, str):
                continue
            url = resolve_url(base_url, same)
            if not url:
                continue
            platform = classify_social_link(url)
            if platform and platform not in links:
                links[platform] = url
    return links


def extract_social_links(soup: BeautifulSoup, base_url: str, container=None) -> list[dict]:
    """Return deduplicated {platform, url} entries from anchor hrefs and JSON-LD sameAs.

    `container` limits anchor scanning to a region (or list of regions), which
    avoids picking up the site's own footer/nav social accounts. JSON-LD sameAs
    is only taken from Person nodes (i.e. the author, not the publisher).
    """
    scopes = container if isinstance(container, list) else ([container] if container is not None else None)
    links = _collect_social_from_anchors(soup, base_url, scopes)
    links.update(_collect_social_from_sameas(soup, base_url))
    return [{"platform": key, "url": links[key]} for key in sorted(links)]


def extract_json_ld(soup: BeautifulSoup) -> list:
    """Parse all <script type="application/ld+json"> blocks, ignoring bad ones."""
    blocks = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        if not raw:
            continue
        for attempt in (raw, raw.strip("/* */"), raw.replace("//<![CDATA[", "").replace("//]]>", "")):
            try:
                blocks.append(json.loads(attempt))
                break
            except (json.JSONDecodeError, TypeError):
                continue
    return blocks


def iter_all_nodes(data):
    """Recursively yield every dict node in a JSON-LD structure."""
    if isinstance(data, list):
        for item in data:
            yield from iter_all_nodes(item)
    elif isinstance(data, dict):
        yield data
        for value in data.values():
            yield from iter_all_nodes(value)


def iter_ld_type(blocks, type_name: str):
    """Yield JSON-LD nodes whose @type contains type_name."""
    for block in blocks:
        for node in iter_all_nodes(block):
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            types = t if isinstance(t, list) else ([t] if t else [])
            if any(type_name in str(x) for x in types):
                yield node


def iter_ld_persons(blocks):
    yield from iter_ld_type(blocks, "Person")


def iter_ld_organizations(blocks):
    yield from iter_ld_type(blocks, "Organization")


def _first_selector_text(soup: BeautifulSoup, selectors) -> str | None:
    for sel in selectors:
        el = soup.select_one(sel)
        if el is not None:
            text = el.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            if text:
                return text
    return None


def _site_names(soup: BeautifulSoup) -> set[str]:
    """Publication names an <h1> might show instead of the author's."""
    names: set[str] = set()
    for attr, value in (("property", "og:site_name"), ("name", "application-name")):
        meta = soup.find("meta", attrs={attr: value})
        if meta is None:
            continue
        content = (meta.get("content") or "").strip().lower()
        if content:
            names.add(content)
    return names


def extract_name(soup: BeautifulSoup, blocks: list) -> str | None:
    for person in iter_ld_persons(blocks):
        name = person.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    # On many pages the <h1> is the publication rather than the person, so it
    # is only used when it does not simply repeat the site name.
    site_names = _site_names(soup)
    h1 = soup.find("h1")
    if h1 is not None:
        text = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
        if text and len(text) < 80 and text.strip().lower() not in site_names:
            return text
    for m in soup.find_all("meta"):
        content = (m.get("content") or "").strip()
        key = (m.get("name") or m.get("property") or "").lower()
        if key in ("author", "byl", "byline", "parsely-author") and content:
            if len(content) < 80:
                return content
    return None


# Role descriptions as they appear in author bios.
_BIO_JOB_PATTERNS = (
    # "Rafael Nam is NPR's Senior Business Editor" / "Daniel Boffey is the Guardian's chief reporter"
    re.compile(r"\bis\s+(?:the\s+)?[A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3}'s\s+([^.,;]{3,60})"),
    # "Zoey Becker is a staff writer for Fierce Pharma Marketing"
    re.compile(
        r"\bis\s+(?:a|an)\s+([^.,;]{3,60}?)"
        r"(?:\s+(?:for|at|with|of|covering|focused\s+on|focusing\s+on|who)\b|[,.;]|$)",
        re.IGNORECASE,
    ),
)


_BIO_ORG_STARTERS = {"the", "a", "an", "this", "that", "our", "its"}


def _job_title_from_bio(bio: str | None, name: str | None) -> str | None:
    """Derive a role from bio prose when no structured job title exists."""
    if not bio:
        return None
    tokens = _name_tokens(name)
    bio_lower = bio[:120].lower()
    name_in_bio = tokens and any(token in bio_lower for token in tokens)
    if not name_in_bio:
        bio_stripped = bio.strip()
        if not bio_stripped or not bio_stripped[0].isalpha():
            return None
        first_word_match = re.match(r"(\w+)\s+", bio_stripped)
        if first_word_match and first_word_match.group(1).lower() in _BIO_ORG_STARTERS:
            return None
        if not re.match(r"^[A-Z][\w'\u00C0-\u024F.\-]+(\s+[A-Z][\w'\u00C0-\u024F.\-]+){0,3}\s+", bio):
            return None
    for pattern in _BIO_JOB_PATTERNS:
        match = pattern.search(bio)
        if not match:
            continue
        role = re.sub(r"\s+", " ", match.group(1).strip(" \t,;."))
        if 3 <= len(role) <= 60:
            return role
    return None


def extract_job_title(
    soup: BeautifulSoup,
    blocks: list,
    name: str | None = None,
    bio: str | None = None,
) -> str | None:
    for person in iter_ld_persons(blocks):
        jt = person.get("jobTitle")
        if isinstance(jt, str) and jt.strip():
            return jt.strip()
    by_selector = _first_selector_text(soup, JOB_TITLE_SELECTORS)
    if by_selector:
        return by_selector
    return _job_title_from_bio(bio, name)


def _link_density(el) -> float:
    """Fraction of an element's text that sits inside links (1.0 = all links)."""
    total = len(el.get_text(" ", strip=True))
    if not total:
        return 1.0
    linked = sum(len(a.get_text(" ", strip=True)) for a in el.find_all("a"))
    return linked / total


# A "<p>" this long and this free of links is prose, not a link list.
_PROSE_MIN_CHARS = 80
_PROSE_MAX_LINK_DENSITY = 0.5


def _is_prose_citation(anchor) -> bool:
    """Is this anchor a link inside running text (a citation, not an account)?

    A social URL mentioned inside the author's bio almost always refers to an
    organisation the author is writing about, whereas the author's own accounts
    are listed in dedicated <li>/<ul>/<nav> social blocks. Treating the former
    as a contact is how a bio citation becomes a false attribution.
    """
    paragraph = anchor.find_parent("p")
    if paragraph is None:
        return False
    text = paragraph.get_text(" ", strip=True)
    return len(text) >= _PROSE_MIN_CHARS and _link_density(paragraph) < _PROSE_MAX_LINK_DENSITY


def extract_bio(soup: BeautifulSoup, blocks: list) -> str | None:
    for person in iter_ld_persons(blocks):
        desc = person.get("description")
        if isinstance(desc, str) and len(desc.strip()) >= 20:
            return re.sub(r"\s+", " ", _strip_tags(desc).strip())[:2000]
    meta = soup.find("meta", attrs={"name": re.compile(r"^(description|author-description)$", re.IGNORECASE)})
    if meta is not None and (meta.get("content") or "").strip():
        desc = _strip_tags(meta["content"]).strip()
        if len(desc) >= 20:
            return re.sub(r"\s+", " ", desc)[:2000]
    for sel in BIO_SELECTORS:
        el = soup.select_one(sel)
        if el is None:
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if len(text) >= 20:
            return text[:2000]
    # Fallback: the longest substantial paragraph that reads like prose. Article
    # listings (link-heavy list items) are skipped, otherwise an excerpt of a
    # story the author wrote would be mistaken for their bio.
    container = soup.find("main") or soup.find("article") or soup
    best = None
    for p in container.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(text) <= 50:
            continue
        if p.find_parent("li") is not None or _link_density(p) > 0.5:
            continue
        if best is None or len(text) > len(best):
            best = text
    return best[:2000] if best else None


def extract_location(soup: BeautifulSoup, blocks: list) -> str | None:
    for person in iter_ld_persons(blocks):
        addr = person.get("address")
        if isinstance(addr, dict):
            loc = addr.get("addressLocality") or addr.get("addressRegion") or addr.get("name")
            if isinstance(loc, str) and loc.strip():
                return loc.strip()
    return _first_selector_text(soup, LOCATION_SELECTORS)


def extract_organization(soup: BeautifulSoup, blocks: list) -> str | None:
    for person in iter_ld_persons(blocks):
        for key in ("worksFor", "affiliation", "memberOf"):
            org = person.get(key)
            if isinstance(org, dict) and isinstance(org.get("name"), str) and org["name"].strip():
                return org["name"].strip()
            if isinstance(org, str) and org.strip():
                return org.strip()
    for org in iter_ld_organizations(blocks):
        name = org.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    if og_site is not None and (og_site.get("content") or "").strip():
        return og_site["content"].strip()
    app = soup.find("meta", attrs={"name": "application-name"})
    if app is not None and (app.get("content") or "").strip():
        return app["content"].strip()
    return None


def extract_author_page(soup: BeautifulSoup, page_url: str) -> dict:
    """Extract structured author info from an author/profile page."""
    blocks = extract_json_ld(soup)
    anchor = _collect_social_from_anchors(soup, page_url, _author_scope(soup))
    if not anchor:
        # No recognizable author container: fall back to the content region.
        anchor = _collect_social_from_anchors(soup, page_url, _main_scope(soup))
    anchor.update(_collect_social_from_sameas(soup, page_url))
    socials = [{"platform": key, "url": anchor[key]} for key in sorted(anchor)]
    by_platform = {s["platform"]: s["url"] for s in socials}
    name = extract_name(soup, blocks)
    bio = extract_bio(soup, blocks)
    emails = _rank_emails(extract_emails(soup), name, page_url)

    person_email = next(
        (str(p.get("email")).strip() for p in iter_ld_persons(blocks) if p.get("email")),
        None,
    )
    email = person_email or (emails[0] if emails else None)

    return {
        "name": name,
        "profile_url": page_url,
        "job_title": extract_job_title(soup, blocks, name, bio),
        "bio": bio,
        "email": email,
        "linkedin": by_platform.get("linkedin"),
        "twitter": by_platform.get("twitter"),
        "social_links": socials,
        "organization": extract_organization(soup, blocks),
        "location": extract_location(soup, blocks),
    }