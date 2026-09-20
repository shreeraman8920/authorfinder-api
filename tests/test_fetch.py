import pytest
import requests

from authorfinder.fetch import (
    BlockedError,
    Fetcher,
    _looks_like_challenge,
    _safe_decode,
)


def test_safe_decode_utf8():
    assert _safe_decode("héllo wörld".encode("utf-8"), "utf-8") == "héllo wörld"


def test_safe_decode_cp1252_declared_as_utf8():
    # Smart quotes / apostrophes stored as Windows-1252 bytes but served with
    # a UTF-8 declaration would normally produce U+FFFD; the decoder must recover.
    raw = "Fierce Pharma\u2019s COVID Tracker".encode("cp1252")
    assert _safe_decode(raw, "utf-8") == "Fierce Pharma\u2019s COVID Tracker"


def test_safe_decode_latin1_declared_windows():
    raw = "caf\u00e9".encode("latin-1")
    assert _safe_decode(raw, "windows-1252") == "caf\u00e9"


def test_safe_decode_ascii():
    assert _safe_decode(b"plain ascii text", None) == "plain ascii text"


# ── Fetching: retries, refusals, and challenge pages ────────────────────────


class _FakeResponse:
    def __init__(self, status_code, text="some page content", headers=None):
        self.status_code = status_code
        self.encoding = "utf-8"
        self.content = text.encode("utf-8")
        self.headers = headers or {}
        self.url = "https://news.example.com/story"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def _fetcher(responses, **kwargs):
    # backoff=0 keeps the retry tests instant.
    fetcher = Fetcher(use_playwright=False, delay=0, backoff=0.0, **kwargs)
    fetcher.session = _FakeSession(responses)
    return fetcher


def test_static_fetch_retries_transient_then_succeeds():
    fetcher = _fetcher([_FakeResponse(503), _FakeResponse(200, "<html>ok</html>")])
    result = fetcher._fetch_static("https://news.example.com/story")
    assert result.status_code == 200
    assert fetcher.session.calls == 2


def test_static_fetch_refusal_is_a_block_not_an_error():
    fetcher = _fetcher([_FakeResponse(403)])
    with pytest.raises(BlockedError):
        fetcher._fetch_static("https://news.example.com/story")
    assert fetcher.session.calls == 1


def test_static_fetch_rate_limit_is_blocked_once_retries_run_out():
    fetcher = _fetcher([_FakeResponse(429)] * 3, max_retries=2)
    with pytest.raises(BlockedError):
        fetcher._fetch_static("https://news.example.com/story")
    assert fetcher.session.calls == 3


def test_static_fetch_honours_retry_after_header():
    fetcher = _fetcher([_FakeResponse(429, headers={"Retry-After": "7"})])
    assert fetcher._retry_delay(fetcher.session._responses[0], 0) == 7.0


def test_static_fetch_detects_bot_challenge_page():
    html = "<html><head><title>Just a moment...</title></head><body>wait</body></html>"
    fetcher = _fetcher([_FakeResponse(200, html)])
    with pytest.raises(BlockedError):
        fetcher._fetch_static("https://news.example.com/story")


def test_looks_like_challenge_distinguishes_real_content():
    assert _looks_like_challenge("<html><head><title>Just a moment...</title></head></html>")
    assert _looks_like_challenge(
        '<html><head><title>News</title></head><body><div id="cf-chl"></div></body></html>'
    )
    assert not _looks_like_challenge(
        "<html><head><title>Climate report</title></head><body><p>By Jane Doe</p></body></html>"
    )