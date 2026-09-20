"""Page fetching with requests (static) and an optional Playwright (JS) fallback.

Requests are rate-limited (small delay), time-bounded, and gated by robots.txt.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# Transient statuses worth another attempt, vs. explicit refusals to stop on.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
BLOCKED_STATUS = frozenset({401, 403, 451})
RATE_LIMIT_STATUS = 429

# Bot-protection interstitials: matched against the <title> (conservative) and
# against very specific markers only found in challenge markup.
_CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "verify you are human",
    "are you a robot",
    "ddos protection",
    "access denied",
    "security check",
    "please wait",
    "loading",
    "verifying",
    "one more step",
    "additional verification",
    "performing security",
    "connection is secure",
)
_CHALLENGE_BODY_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "enable javascript and cookies to continue",
    "cf-browser-verification",
    "cf_chl_opt",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "challenge-running",
    "datadome",
    "perimeterx",
    "incapsula",
    "_Incapsula_Resource",
    "px-captcha",
)

# Paywall indicators: keywords and markup patterns that signal gated content.
_PAYWALL_TITLE_MARKERS = (
    "subscribe to continue",
    "subscriber-only",
    "member-only",
    "premium content",
    "this article is for subscribers",
    "sign in to read",
    "create an account",
    "join to read",
    "support quality journalism",
    "unlimited access",
    "premium article",
)
_PAYWALL_BODY_MARKERS = (
    "subscribe to continue reading",
    "this article is available to subscribers",
    " members-only content",
    "premium content for subscribers",
    "sign in to access this article",
    "create a free account to continue",
    "register for free to continue reading",
    "subscribe now to continue",
    "this content is for subscribers only",
    "article for subscribers",
    "paywall",
    "metered-wall",
    "registration-wall",
)

# Cookie/consent banners that cover the article until dismissed.
_CONSENT_SELECTORS = (
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "[data-testid='accept-cookies']",
    "[data-cy='accept-cookies']",
    "#gdpr-banner-accept",
    ".cc-allow",
    ".qc-cmp2-summary-buttons button",
)


class BlockedError(PermissionError):
    """Raised when a site refuses the request.

    Covers robots.txt disallowal, explicit refusals (401/403/451), rate
    limiting that survives retries, and bot-protection challenge pages.
    """


class RobotsError(BlockedError):
    """Raised when robots.txt disallows fetching a URL."""


class PaywallError(BlockedError):
    """Raised when content is behind a paywall or registration wall."""


@dataclass
class FetchResult:
    url: str  # requested URL
    html: str  # fetched HTML
    status_code: int
    final_url: str  # URL after redirects


class RobotsChecker:
    """Minimal robots.txt checker with per-origin caching."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 5.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser | None] = {}

    def _load(self, origin: str) -> RobotFileParser | None:
        try:
            resp = requests.get(
                origin + "/robots.txt",
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
            )
            parser = RobotFileParser()
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                # No robots.txt -> treat as allow-all.
                parser = None
        except requests.RequestException as exc:
            log.debug("Could not fetch robots.txt for %s: %s", origin, exc)
            parser = None
        self._parsers[origin] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._parsers.get(origin)
        if parser is None and origin not in self._parsers:
            parser = self._load(origin)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)


def _has_content(html: str) -> bool:
    """Rough check: does the HTML contain a meaningful amount of text?"""
    if not html or not html.strip():
        return False
    soup = BeautifulSoup(html, "html.parser")
    for bad in ("script", "style", "noscript", "svg", "head"):
        for tag in soup.find_all(bad):
            tag.decompose()
    return len(soup.get_text(" ", strip=True)) >= 200


def _charset_from_content_type(content_type: str) -> str | None:
    m = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", content_type, re.IGNORECASE)
    return m.group(1) if m else None


# Non-characters / replacement chars that indicate a decoding problem (or data
# corrupted by the publisher itself).
_BAD_CHARS = ("\ufffd", "\ufffe", "\uffff")


def _has_bad_chars(text: str) -> bool:
    return any(c in text for c in _BAD_CHARS)


def _looks_like_challenge(html: str) -> bool:
    """Heuristic: is this HTML a bot-protection interstitial, not real content?"""
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").lower()
    if any(marker in title for marker in _CHALLENGE_TITLE_MARKERS):
        return True
    head = html[:8000].lower()
    return any(marker in head for marker in _CHALLENGE_BODY_MARKERS)


def _looks_like_paywall(html: str) -> bool:
    """Heuristic: is this HTML a paywall/registration wall?"""
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").lower()
    if any(marker in title for marker in _PAYWALL_TITLE_MARKERS):
        return True
    body_text = soup.get_text(" ", strip=True).lower()[:20000]
    return any(marker in body_text for marker in _PAYWALL_BODY_MARKERS)


def _dismiss_consent(page) -> None:
    """Best-effort: click away a consent banner that hides the article."""
    for selector in _CONSENT_SELECTORS:
        try:
            button = page.query_selector(selector)
            if button is None:
                continue
            button.click(timeout=1500)
            log.debug("Dismissed consent banner via %s", selector)
            return
        except Exception:  # noqa: BLE001 - a stubborn banner must never abort the fetch
            continue
    try:
        button = page.query_selector("button:has-text('Accept')")
        if button is not None:
            button.click(timeout=1500)
            log.debug("Dismissed consent banner via button text")
    except Exception:  # noqa: BLE001
        pass


def _wait_for_content(page, timeout: float, min_chars: int = 200) -> None:
    """Wait until the rendered page actually has text (SPAs hydrate late)."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=min(timeout, 10) * 1000)
    except Exception:  # noqa: BLE001
        pass
    deadline = time.monotonic() + min(timeout, 10.0)
    scrolled = False
    while True:
        try:
            text = page.inner_text("body")
        except Exception:  # noqa: BLE001
            text = ""
        if len(text.strip()) >= min_chars:
            return
        if time.monotonic() >= deadline:
            return
        if not scrolled:
            # A single scroll nudges lazy-loaded content into place.
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:  # noqa: BLE001
                pass
            scrolled = True
        page.wait_for_timeout(250)


def _safe_decode(content: bytes, declared: str | None) -> str:
    """Decode HTML bytes robustly.

    Some sites declare UTF-8 but actually serve Windows-1252 bytes (or vice
    versa), which yields U+FFFD replacement characters. Try the declared
    charset first, then common encodings, and keep the first clean decode.
    """
    candidates: list[str] = []
    if declared and declared.lower() not in ("iso-8859-1", "latin-1", "windows-1252"):
        candidates.append(declared)
    candidates.extend(("utf-8", "utf-8-sig", "cp1252", "windows-1252", "latin-1"))
    for enc in candidates:
        try:
            text = content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
        if not _has_bad_chars(text):
            return text
    return content.decode("utf-8", errors="replace")


class Fetcher:
    """Fetch a page statically; fall back to a headless browser when needed."""

    def __init__(
        self,
        use_playwright: bool = True,
        delay: float = 1.0,
        timeout: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 2,
        backoff: float = 1.5,
    ):
        self.use_playwright = use_playwright
        self.delay = delay
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max(0, max_retries)
        self.backoff = max(0.0, backoff)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self.robots = RobotsChecker(user_agent)

    def fetch(self, url: str) -> FetchResult:
        if not self.robots.can_fetch(url):
            log.info("Blocked by robots.txt: %s", url)
            raise RobotsError(f"robots.txt disallows fetching {url}")
        time.sleep(self.delay)

        static_result = None
        static_error: Exception | None = None
        try:
            static_result = self._fetch_static(url)
        except (BlockedError, requests.RequestException) as exc:
            static_error = exc
            log.debug("Static fetch of %s failed (%s); trying browser.", url, exc)

        # A static refusal (403 / rate limit / challenge) is often just this
        # client being told no; a real browser frequently gets through, so the
        # browser is attempted whenever the static page is unusable.
        needs_browser = static_result is None or not _has_content(static_result.html)
        if needs_browser and self.use_playwright:
            try:
                js_result = self._fetch_js(url)
            except Exception as exc:  # noqa: BLE001 - any browser failure falls back
                log.warning("Browser fetch of %s failed (%s); falling back to static.", url, exc)
                if isinstance(exc, BlockedError) and static_result is None:
                    static_error = exc
                elif static_result is None and static_error is None:
                    static_error = exc
            else:
                if static_result is None or _has_content(js_result.html):
                    return js_result

        if static_result is None:
            if static_error is not None:
                raise static_error
            raise RuntimeError(f"Failed to fetch {url}")
        return static_result

    def _retry_delay(self, resp, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After") if resp is not None else None
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except (TypeError, ValueError):
                pass
        return min(self.backoff * (2 ** attempt), 30.0)

    def _fetch_static(self, url: str) -> FetchResult:
        for attempt in range(self.max_retries + 1):
            resp = self.session.get(url, timeout=(self.timeout, self.timeout))
            if resp.status_code in BLOCKED_STATUS:
                raise BlockedError(f"site refused the request ({resp.status_code}) for {url}")
            if resp.status_code in RETRYABLE_STATUS:
                if attempt < self.max_retries:
                    delay = self._retry_delay(resp, attempt)
                    log.debug(
                        "Transient HTTP %s for %s; retrying in %.1fs",
                        resp.status_code,
                        url,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code == RATE_LIMIT_STATUS:
                    raise BlockedError(f"rate limited ({resp.status_code}) for {url}")
            resp.raise_for_status()
            html = _safe_decode(resp.content, resp.encoding)
            if _looks_like_challenge(html):
                raise BlockedError(f"bot-protection challenge detected for {url}")
            if _looks_like_paywall(html):
                raise PaywallError(f"paywall detected for {url}")
            return FetchResult(
                url=url, html=html, status_code=resp.status_code, final_url=resp.url
            )
        # Unreachable in practice: the loop only exits via return or raise.
        raise requests.HTTPError(f"no successful response for {url}")

    def _fetch_js(self, url: str) -> FetchResult:
        import sys
        frozen = getattr(sys, "frozen", False)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            log.warning("Playwright not installed; cannot use browser fallback for %s", url)
            raise RuntimeError(
                "Playwright is not installed. Run: pip install 'authorfinder[playwright]' "
                "and then 'python -m playwright install chromium'."
            ) from exc
        log.debug("Launching Playwright browser for %s", url)
        with sync_playwright() as p:
            # In a .exe, Chromium isn't bundled — use system Chrome instead.
            channel = "chrome" if frozen else None
            browser = p.chromium.launch(headless=True, channel=channel)
            try:
                context = browser.new_context(
                    user_agent=self.user_agent,
                    locale="en-US",
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                resp = page.goto(url, timeout=int(self.timeout * 1000), wait_until="domcontentloaded")
                _dismiss_consent(page)
                _wait_for_content(page, self.timeout)
                html = page.content()
                if _has_bad_chars(html) and resp is not None:
                    # The browser decoded per the declared charset; if that
                    # produced mojibake, re-decode the raw response bytes.
                    try:
                        body = resp.body()
                    except Exception:
                        body = None
                    if body:
                        declared = _charset_from_content_type(str(resp.headers.get("content-type", "")))
                        decoded = _safe_decode(body, declared)
                        if not _has_bad_chars(decoded):
                            html = decoded
                final_url = page.url
                status = resp.status if resp is not None else None
                if status in BLOCKED_STATUS or _looks_like_challenge(html):
                    raise BlockedError(
                        f"site blocked the browser request ({status}) for {url}"
                    )
                if _looks_like_paywall(html):
                    raise PaywallError(f"paywall detected in browser for {url}")
            finally:
                browser.close()
        log.debug("Playwright fetched %s (status=%s)", url, status)
        return FetchResult(url=url, html=html, status_code=status or 0, final_url=final_url)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")