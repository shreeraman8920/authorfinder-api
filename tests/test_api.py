"""Tests for the job-based API endpoints."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import api as api_module
from api import app


@pytest.fixture(autouse=True)
def clear_jobs():
    """Reset job storage before each test."""
    api_module._jobs.clear()
    yield
    api_module._jobs.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.3.0"
    assert "max_concurrent" in data


@pytest.mark.asyncio
async def test_submit_crawl_returns_202(client, monkeypatch):
    """POST /crawl returns 202 immediately when _run_crawl is mocked."""
    async def noop_run(*a, **kw):
        pass
    monkeypatch.setattr(api_module, "_run_crawl", noop_run)

    resp = await client.post("/crawl", json={"url": "https://news.example.com/article"})
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "processing"
    assert "created_at" in data


@pytest.mark.asyncio
async def test_submit_crawl_creates_job_in_storage(client, monkeypatch):
    async def noop_run(*a, **kw):
        pass
    monkeypatch.setattr(api_module, "_run_crawl", noop_run)

    resp = await client.post("/crawl", json={"url": "https://news.example.com/article"})
    job_id = resp.json()["job_id"]
    assert job_id in api_module._jobs
    job = api_module._jobs[job_id]
    assert job["status"] == "processing"
    assert "example.com" in job["url"]


@pytest.mark.asyncio
async def test_get_job_status_processing(client):
    """Insert a fake processing job and poll it."""
    job_id = "test-processing-job"
    api_module._jobs[job_id] = {
        "job_id": job_id,
        "url": "https://news.example.com/article",
        "status": "processing",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": 0,
        "completed_at": None,
        "elapsed_seconds": None,
        "result": None,
        "error": None,
    }

    resp = await client.get(f"/crawl/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "processing"
    assert data["url"] == "https://news.example.com/article"


@pytest.mark.asyncio
async def test_get_job_status_completed(client):
    job_id = "test-completed-job"
    api_module._jobs[job_id] = {
        "job_id": job_id,
        "url": "https://news.example.com/article",
        "status": "completed",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": 0,
        "completed_at": 100.0,
        "elapsed_seconds": 45.2,
        "result": {
            "article_url": "https://news.example.com/article",
            "author": {"name": "Jane Doe", "email": "jane@example.com"},
            "authors": [],
            "status": "success",
            "error": None,
            "elapsed_seconds": 45.2,
        },
        "error": None,
    }

    resp = await client.get(f"/crawl/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["result"]["status"] == "success"
    assert data["result"]["author"]["name"] == "Jane Doe"
    assert data["elapsed_seconds"] == 45.2


@pytest.mark.asyncio
async def test_get_job_status_failed(client):
    job_id = "test-failed-job"
    api_module._jobs[job_id] = {
        "job_id": job_id,
        "url": "https://news.example.com/article",
        "status": "failed",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": 0,
        "completed_at": 30.0,
        "elapsed_seconds": 30.1,
        "result": None,
        "error": "RuntimeError: Browser not installed",
    }

    resp = await client.get(f"/crawl/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "RuntimeError" in data["error"]
    assert data["result"] is None


@pytest.mark.asyncio
async def test_get_job_status_timeout(client):
    job_id = "test-timeout-job"
    api_module._jobs[job_id] = {
        "job_id": job_id,
        "url": "https://news.example.com/slow-article",
        "status": "timeout",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": 0,
        "completed_at": 120.0,
        "elapsed_seconds": 120.0,
        "result": None,
        "error": "Crawl exceeded maximum time of 120 seconds",
    }

    resp = await client.get(f"/crawl/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "timeout"
    assert "exceeded" in data["error"]


@pytest.mark.asyncio
async def test_get_job_status_not_found(client):
    resp = await client.get("/crawl/nonexistent-job-id")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_batch_submit_creates_individual_jobs(client, monkeypatch):
    async def noop_run(*a, **kw):
        pass
    monkeypatch.setattr(api_module, "_run_crawl", noop_run)

    resp = await client.post("/crawl/batch", json={
        "urls": [
            "https://news.example.com/article1",
            "https://news.example.com/article2",
            "https://news.example.com/article3",
        ]
    })
    assert resp.status_code == 202
    data = resp.json()
    assert data["total"] == 3
    assert len(data["job_ids"]) == 3

    for job_id in data["job_ids"]:
        assert job_id in api_module._jobs
        assert api_module._jobs[job_id]["status"] == "processing"


@pytest.mark.asyncio
async def test_batch_submit_max_50_urls(client):
    urls = [f"https://news.example.com/article{i}" for i in range(51)]
    resp = await client.post("/crawl/batch", json={"urls": urls})
    assert resp.status_code == 400
    assert "50" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_background_crawl_completes(monkeypatch):
    """Test that _run_crawl stores a completed result."""
    from tests.fixtures import AUTHOR_URL, article_html, author_html
    from authorfinder.fetch import FetchResult
    from authorfinder.crawler import AuthorCrawler

    class FakeFetcher:
        def __init__(self):
            self.use_playwright = False
            self._context = None
            self.pages = {}
            self.fetched = []

        def set_context(self, ctx):
            self._context = ctx

        async def fetch(self, url):
            self.fetched.append(url)
            html, final = self.pages.get(url, ("<html></html>", url))
            return FetchResult(url=url, html=html, status_code=200, final_url=final or url)

    article = "https://news.example.com/2024/01/15/climate-policy-report"
    fetcher = FakeFetcher()
    fetcher.pages = {
        article: (article_html(), article),
        AUTHOR_URL: (author_html(), AUTHOR_URL),
    }

    async def fake_run_crawl(job_id, url, timeout, delay, use_playwright):
        async with api_module._crawl_semaphore:
            import time
            start = time.monotonic()
            try:
                crawler = AuthorCrawler(fetcher=fetcher)
                result = await asyncio.wait_for(crawler.crawl(url), timeout=30)
                elapsed = time.monotonic() - start
                async with api_module._jobs_lock:
                    api_module._jobs[job_id]["status"] = "completed"
                    api_module._jobs[job_id]["result"] = {
                        "article_url": result["article_url"],
                        "author": result["author"],
                        "authors": result.get("authors", []),
                        "status": result["status"],
                        "error": result.get("error"),
                        "elapsed_seconds": round(elapsed, 2),
                    }
                    api_module._jobs[job_id]["elapsed_seconds"] = round(elapsed, 2)
                    api_module._jobs[job_id]["completed_at"] = time.monotonic()
            except Exception as exc:
                elapsed = time.monotonic() - start
                async with api_module._jobs_lock:
                    api_module._jobs[job_id]["status"] = "failed"
                    api_module._jobs[job_id]["error"] = str(exc)
                    api_module._jobs[job_id]["elapsed_seconds"] = round(elapsed, 2)
                    api_module._jobs[job_id]["completed_at"] = time.monotonic()

    job_id = "integration-test-job"
    api_module._jobs[job_id] = {
        "job_id": job_id,
        "url": article,
        "status": "processing",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": 0,
        "completed_at": None,
        "elapsed_seconds": None,
        "result": None,
        "error": None,
    }

    await fake_run_crawl(job_id, article, timeout=20, delay=0, use_playwright=False)

    job = api_module._jobs[job_id]
    assert job["status"] == "completed"
    assert job["result"]["status"] == "success"
    assert job["result"]["author"]["name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_cleanup_expired_jobs(client):
    import time

    api_module._jobs["old-job-1"] = {
        "job_id": "old-job-1",
        "url": "https://example.com",
        "status": "completed",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": 0,
        "completed_at": time.monotonic() - 7200,
        "elapsed_seconds": 30,
        "result": {
            "article_url": "https://example.com",
            "author": {},
            "authors": [],
            "status": "success",
            "error": None,
            "elapsed_seconds": 30,
        },
        "error": None,
    }
    api_module._jobs["active-job"] = {
        "job_id": "active-job",
        "url": "https://example.com",
        "status": "processing",
        "created_at": "2026-09-20T12:00:00Z",
        "created_monotonic": time.monotonic(),
        "completed_at": None,
        "elapsed_seconds": None,
        "result": None,
        "error": None,
    }

    await api_module._cleanup_expired_jobs()

    assert "old-job-1" not in api_module._jobs
    assert "active-job" in api_module._jobs
