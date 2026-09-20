"""AuthorFinder API — Extract journalist/author contact info from news article URLs.

Run:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Docs:
    http://localhost:8000/docs        (Swagger UI)
    http://localhost:8000/redoc       (ReDoc)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, HttpUrl

from authorfinder.crawler import AuthorCrawler

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("AUTHORFINDER_API_KEY", "")
MAX_CONCURRENT = int(os.environ.get("AUTHORFINDER_MAX_CONCURRENT", "5"))
DEFAULT_TIMEOUT = float(os.environ.get("AUTHORFINDER_TIMEOUT", "20"))
DEFAULT_DELAY = float(os.environ.get("AUTHORFINDER_DELAY", "1.5"))
CRAWL_TIMEOUT = float(os.environ.get("AUTHORFINDER_CRAWL_TIMEOUT", "60"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("authorfinder.api")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AuthorFinder API",
    description="Extract journalist/author contact information from news article URLs.",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── Models ────────────────────────────────────────────────────────────────────
class CrawlRequest(BaseModel):
    url: HttpUrl
    timeout: Optional[float] = DEFAULT_TIMEOUT
    delay: Optional[float] = DEFAULT_DELAY
    use_playwright: bool = True

    model_config = {"json_schema_extra": {"examples": [{"url": "https://www.statnews.com/2026/06/13/who-director-general-in-drc-war-greater-concern-than-ebola/"}]}}


class BatchCrawlRequest(BaseModel):
    urls: list[HttpUrl]
    timeout: Optional[float] = DEFAULT_TIMEOUT
    delay: Optional[float] = DEFAULT_DELAY
    use_playwright: bool = True

    model_config = {"json_schema_extra": {"examples": [{"urls": ["https://www.statnews.com/2026/06/13/who-director-general-in-drc-war-greater-concern-than-ebola/", "https://endpoints.news/merck-brings-welireg-keytruda-combo-to-treat-kidney-cancer/"]}]}}


class AuthorInfo(BaseModel):
    name: str | None = None
    profile_url: str | None = None
    job_title: str | None = None
    bio: str | None = None
    email: str | None = None
    linkedin: str | None = None
    twitter: str | None = None
    social_links: list[dict] = []
    organization: str | None = None
    location: str | None = None


class CrawlResponse(BaseModel):
    article_url: str
    author: AuthorInfo
    authors: list[AuthorInfo] = []
    status: str
    error: str | None = None
    elapsed_seconds: float


class BatchCrawlResponse(BaseModel):
    results: list[CrawlResponse]
    total: int
    success_count: int
    failed_count: int
    elapsed_seconds: float


class HealthResponse(BaseModel):
    status: str
    version: str
    max_concurrent: int


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check API health and version."""
    return HealthResponse(
        status="ok",
        version="0.2.0",
        max_concurrent=MAX_CONCURRENT,
    )


@app.post("/crawl", response_model=CrawlResponse, tags=["Crawl"])
async def crawl_article(req: CrawlRequest, _=Depends(verify_api_key)):
    """Extract author information from a single news article URL."""
    start = time.monotonic()
    try:
        crawler = AuthorCrawler(
            use_playwright=req.use_playwright,
            timeout=req.timeout,
            delay=req.delay,
        )
        result = await asyncio.wait_for(
            crawler.crawl(str(req.url)),
            timeout=CRAWL_TIMEOUT,
        )
        elapsed = time.monotonic() - start
        return CrawlResponse(
            article_url=result["article_url"],
            author=AuthorInfo(**result["author"]),
            authors=[AuthorInfo(**a) for a in result.get("authors", [])],
            status=result["status"],
            error=result.get("error"),
            elapsed_seconds=round(elapsed, 2),
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        log.warning("Crawl of %s timed out after %.1fs", req.url, elapsed)
        raise HTTPException(status_code=504, detail=f"Crawl timed out after {CRAWL_TIMEOUT}s")
    except Exception as exc:
        log.exception("Crawl failed for %s", req.url)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/crawl/batch", response_model=BatchCrawlResponse, tags=["Crawl"])
async def crawl_batch(req: BatchCrawlRequest, _=Depends(verify_api_key)):
    """Extract author information from multiple news article URLs (up to 50)."""
    if len(req.urls) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 URLs per batch")

    start = time.monotonic()

    async def _crawl_one(url: str) -> CrawlResponse:
        t0 = time.monotonic()
        try:
            crawler = AuthorCrawler(
                use_playwright=req.use_playwright,
                timeout=req.timeout,
                delay=req.delay,
            )
            result = await asyncio.wait_for(
                crawler.crawl(url),
                timeout=CRAWL_TIMEOUT,
            )
            elapsed = time.monotonic() - t0
            return CrawlResponse(
                article_url=result["article_url"],
                author=AuthorInfo(**result["author"]),
                authors=[AuthorInfo(**a) for a in result.get("authors", [])],
                status=result["status"],
                error=result.get("error"),
                elapsed_seconds=round(elapsed, 2),
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            log.warning("Crawl of %s timed out after %.1fs", url, elapsed)
            return CrawlResponse(
                article_url=url,
                author=AuthorInfo(),
                status="timeout",
                error=f"Crawl timed out after {CRAWL_TIMEOUT}s",
                elapsed_seconds=round(elapsed, 2),
            )
        except Exception as exc:
            log.exception("Crawl failed for %s", url)
            elapsed = time.monotonic() - t0
            return CrawlResponse(
                article_url=url,
                author=AuthorInfo(),
                status="error",
                error=str(exc),
                elapsed_seconds=round(elapsed, 2),
            )

    results = await asyncio.gather(*[_crawl_one(str(u)) for u in req.urls])

    elapsed = time.monotonic() - start
    success_count = sum(1 for r in results if r.status == "success")
    return BatchCrawlResponse(
        results=results,
        total=len(results),
        success_count=success_count,
        failed_count=len(results) - success_count,
        elapsed_seconds=round(elapsed, 2),
    )
