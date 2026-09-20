from bs4 import BeautifulSoup

from authorfinder.author import choose_author, detect_authors
from authorfinder.fetch import parse_html

from .fixtures import AUTHOR_URL, article_html


def _soup(html: str) -> BeautifulSoup:
    return parse_html(html)


def test_detect_author_from_article():
    soup = _soup(article_html())
    candidates = detect_authors(soup, "https://news.example.com/2024/01/15/climate-policy-report")
    assert candidates, "expected at least one candidate"
    names = {c.name for c in candidates}
    assert "Jane Doe" in names
    urls = {c.profile_url for c in candidates}
    assert AUTHOR_URL in urls


def test_choose_author_prefers_named_same_site_profile():
    soup = _soup(article_html())
    candidates = detect_authors(soup, "https://news.example.com/2024/01/15/climate-policy-report")
    chosen = choose_author(candidates, "https://news.example.com/2024/01/15/climate-policy-report")
    assert chosen.name == "Jane Doe"
    assert chosen.profile_url == AUTHOR_URL


def test_detect_author_from_meta_only():
    html = """<html><head>
      <meta name="author" content="Bob Smith">
    </head><body><article><p>Story text.</p></article></body></html>"""
    candidates = detect_authors(_soup(html), "https://news.example.com/s1")
    assert any(c.name == "Bob Smith" for c in candidates)


def test_detect_author_rel_attribute():
    html = """<html><body><article>
      <p>By <a rel="author" href="/profile/john-smith/">John Smith</a></p>
    </article></body></html>"""
    candidates = detect_authors(_soup(html), "https://news.example.com/s2")
    chosen = choose_author(candidates, "https://news.example.com/s2")
    assert chosen.name == "John Smith"
    assert chosen.profile_url == "https://news.example.com/profile/john-smith/"


def test_detect_no_author_returns_empty():
    html = """<html><head><title>Just a page</title></head>
    <body><article><p>No author anywhere here.</p></article></body></html>"""
    candidates = detect_authors(_soup(html), "https://news.example.com/s3")
    assert candidates == []


def test_detect_does_not_guess_social_urls_as_profiles():
    html = """<html><body><article>
      <div class="byline">By <a href="https://twitter.com/jane">Jane Doe</a></div>
    </article></body></html>"""
    candidates = detect_authors(_soup(html), "https://news.example.com/s4")
    for c in candidates:
        if c.profile_url:
            assert "twitter.com" not in c.profile_url


def test_detect_ignores_external_meta_author_urls():
    html = """<html><head>
      <meta property="article:author" content="https://www.facebook.com/bbcnews">
      <meta name="author" content="BBC News">
    </head><body><article><p>Story text.</p></article></body></html>"""
    candidates = detect_authors(_soup(html), "https://news.example.com/s5")
    assert not any(c.profile_url for c in candidates)
    assert any(c.name == "BBC News" for c in candidates)