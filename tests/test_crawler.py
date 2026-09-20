import asyncio

import pytest

from authorfinder.crawler import AuthorCrawler
from authorfinder.fetch import BlockedError, FetchResult

from .fixtures import AUTHOR_URL, article_html, author_html, author_html_no_contact


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    async def fetch(self, url):
        self.fetched.append(url)
        html, final = self.pages[url]
        return FetchResult(url=url, html=html, status_code=200, final_url=final or url)


def _crawler(pages):
    return AuthorCrawler(fetcher=FakeFetcher(pages))


@pytest.mark.asyncio
async def test_crawl_full_success():
    article = "https://news.example.com/2024/01/15/climate-policy-report"
    crawler = _crawler(
        {
            article: (article_html(), article),
            AUTHOR_URL: (author_html(), AUTHOR_URL),
        }
    )
    result = await crawler.crawl(article)
    assert result["status"] == "success"
    assert result["article_url"] == article
    author = result["author"]
    assert author["name"] == "Jane Doe"
    assert author["profile_url"] == AUTHOR_URL
    assert author["email"] == "jane.doe@newsexample.com"
    assert author["linkedin"] == "https://www.linkedin.com/in/jane-doe"
    assert author["twitter"] == "https://twitter.com/janedoe"
    assert author["job_title"] == "Senior Reporter"
    assert author["organization"] == "Example News"
    assert author["location"] == "Washington, D.C."
    assert crawler.fetcher.fetched == [article, AUTHOR_URL]


@pytest.mark.asyncio
async def test_crawl_no_author_page_reported():
    article = "https://news.example.com/2024/01/15/another-story"
    html = """<html><head><meta name="author" content="Jane Doe"></head>
    <body><article><p>Story text.</p></article></body></html>"""
    crawler = _crawler({article: (html, article)})
    result = await crawler.crawl(article)
    assert result["status"] == "no_author_page"
    assert result["author"]["name"] == "Jane Doe"
    assert result["author"]["profile_url"] is None


@pytest.mark.asyncio
async def test_crawl_no_author_found():
    article = "https://news.example.com/2024/01/15/anon-story"
    html = """<html><body><article><p>No author byline present at all.</p></article></body></html>"""
    crawler = _crawler({article: (html, article)})
    result = await crawler.crawl(article)
    assert result["status"] == "no_author_found"


@pytest.mark.asyncio
async def test_crawl_reports_blocked_when_the_site_refuses():
    class BlockingFetcher:
        async def fetch(self, url):
            raise BlockedError(f"site refused {url}")

    result = await AuthorCrawler(fetcher=BlockingFetcher()).crawl(
        "https://news.example.com/2024/01/15/story"
    )
    assert result["status"] == "blocked"
    assert "refused" in result["error"]


@pytest.mark.asyncio
async def test_crawl_missing_fields_are_null_or_empty():
    article = "https://news.example.com/2024/01/15/sparse-story"
    html = '<html><body><div class="byline"><a rel="author" href="/author/jane-doe/">Jane Doe</a></div></body></html>'
    crawler = _crawler(
        {
            article: (html, article),
            AUTHOR_URL: (author_html_no_contact(), AUTHOR_URL),
        }
    )
    result = await crawler.crawl(article)
    assert result["status"] == "success"
    author = result["author"]
    assert author["email"] is None
    assert author["linkedin"] is None
    assert author["twitter"] is None
    assert author["social_links"] == []
    assert author["bio"] == "Jane Doe writes for Example News."


class SlowFetcher:
    """Fetcher that hangs long enough to trigger a timeout."""
    async def fetch(self, url):
        await asyncio.sleep(100)
        return FetchResult(url=url, html="", status_code=200, final_url=url)


@pytest.mark.asyncio
async def test_crawl_times_out_when_overall_timeout_exceeded():
    crawler = AuthorCrawler(fetcher=SlowFetcher())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(crawler.crawl("https://news.example.com/slow"), timeout=0.1)


@pytest.mark.asyncio
async def test_crawl_does_not_timeout_when_fast():
    article = "https://news.example.com/2024/01/15/fast-story"
    crawler = _crawler(
        {
            article: (article_html(), article),
            AUTHOR_URL: (author_html(), AUTHOR_URL),
        }
    )
    result = await asyncio.wait_for(crawler.crawl(article), timeout=5.0)
    assert result["status"] == "success"
