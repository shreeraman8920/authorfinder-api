from authorfinder.urls import (
    classify_social_link,
    clean_url,
    looks_like_author_link,
    looks_like_author_page,
    normalize_article_url,
    resolve_url,
    same_domain,
)


def test_resolve_absolute():
    assert resolve_url("https://a.com/x", "https://a.com/author/foo") == "https://a.com/author/foo"


def test_resolve_relative():
    assert resolve_url("https://a.com/news/story", "/author/foo/") == "https://a.com/author/foo/"
    assert resolve_url("https://a.com/news/story", "author/foo") == "https://a.com/news/author/foo"
    assert resolve_url("https://a.com/news/story/", "../author/foo") == "https://a.com/news/author/foo"


def test_resolve_protocol_relative():
    assert resolve_url("https://a.com/x", "//cdn.a.com/img.png") == "https://cdn.a.com/img.png"


def test_resolve_rejects_non_http_schemes():
    for href in ("mailto:x@y.com", "tel:+123", "javascript:void(0)", "data:text/html,x", "sms:555", "#section"):
        assert resolve_url("https://a.com/x", href) is None, href


def test_resolve_cleans_tracking_params():
    url = resolve_url("https://a.com/story", "?utm_source=twitter&utm_medium=social&fbclid=abc&keep=1#frag")
    assert url == "https://a.com/story?keep=1"


def test_same_domain():
    assert same_domain("https://news.example.com/a", "https://news.example.com/b")
    assert same_domain("https://sub.news.example.com/a", "https://news.example.com/b")
    assert not same_domain("https://other.com/a", "https://news.example.com/b")


def test_looks_like_author_page():
    assert looks_like_author_page("https://news.example.com/author/jane-doe/")
    assert looks_like_author_page("https://news.example.com/authors/jane-doe")
    assert looks_like_author_page("https://news.example.com/profile/1234")
    assert looks_like_author_page("https://news.example.com/contributor/jane-doe")
    assert looks_like_author_page("https://author.example.com/jane-doe")
    assert not looks_like_author_page("https://news.example.com/2024/01/15/story")


def test_looks_like_author_page_recognises_more_staff_paths():
    assert looks_like_author_page("https://news.example.com/editor/jane-doe/")
    assert looks_like_author_page("https://news.example.com/correspondent/jane-doe")
    assert looks_like_author_page("https://news.example.com/bios/jane-doe")
    assert looks_like_author_page("https://news.example.com/bloggers/jane-doe")


def test_looks_like_author_link():
    assert looks_like_author_link("Jane Doe", "/author/jane-doe/")
    assert looks_like_author_link("About the author", "/staff/123")
    assert not looks_like_author_link("Climate report", "/2024/01/15/story")


def test_classify_social_link():
    assert classify_social_link("https://www.linkedin.com/in/jane-doe") == "linkedin"
    assert classify_social_link("https://twitter.com/janedoe") == "twitter"
    assert classify_social_link("https://x.com/janedoe") == "twitter"
    assert classify_social_link("https://www.instagram.com/janedoe/") == "instagram"
    assert classify_social_link("https://linkedin.com/company/acme") is None  # not a profile
    assert classify_social_link("https://news.example.com/author/jane-doe/") is None


def test_normalize_article_url():
    assert normalize_article_url("news.example.com/story") == "https://news.example.com/story"
    assert normalize_article_url("https://news.example.com/story") == "https://news.example.com/story"