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
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, HttpUrl

from authorfinder.crawler import AuthorCrawler

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("AUTHORFINDER_API_KEY", "")
MAX_CONCURRENT = int(os.environ.get("AUTHORFINDER_MAX_CONCURRENT", "5"))
DEFAULT_TIMEOUT = float(os.environ.get("AUTHORFINDER_TIMEOUT", "20"))
DEFAULT_DELAY = float(os.environ.get("AUTHORFINDER_DELAY", "1.5"))
CRAWL_TIMEOUT = float(os.environ.get("AUTHORFINDER_CRAWL_TIMEOUT", "120"))
JOB_TTL = float(os.environ.get("AUTHORFINDER_JOB_TTL", "3600"))  # 1 hour

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
    version="0.3.0",
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


# ── Job Storage ───────────────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = asyncio.Lock()
_crawl_semaphore = asyncio.Semaphore(MAX_CONCURRENT)


async def _cleanup_expired_jobs() -> None:
    """Remove completed/failed/timeout jobs older than JOB_TTL."""
    now = time.monotonic()
    async with _jobs_lock:
        expired = [
            jid for jid, job in _jobs.items()
            if job["status"] != "processing"
            and job.get("completed_at") is not None
            and (now - job["completed_at"]) > JOB_TTL
        ]
        for jid in expired:
            del _jobs[jid]
        if expired:
            log.info("Cleaned up %d expired jobs", len(expired))


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


class CrawlResult(BaseModel):
    article_url: str
    author: AuthorInfo
    authors: list[AuthorInfo] = []
    status: str
    error: str | None = None
    elapsed_seconds: float


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    url: str
    created_at: str


class BatchJobSubmitResponse(BaseModel):
    job_ids: list[str]
    total: int


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    url: str
    created_at: str
    elapsed_seconds: float | None = None
    result: CrawlResult | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    max_concurrent: int


# ── Background Crawl Task ────────────────────────────────────────────────────
async def _run_crawl(
    job_id: str,
    url: str,
    timeout: float,
    delay: float,
    use_playwright: bool,
) -> None:
    """Execute a crawl as a background task and store the result."""
    async with _crawl_semaphore:
        start = time.monotonic()
        try:
            crawler = AuthorCrawler(
                use_playwright=use_playwright,
                timeout=timeout,
                delay=delay,
            )
            result = await asyncio.wait_for(
                crawler.crawl(url),
                timeout=CRAWL_TIMEOUT,
            )
            elapsed = time.monotonic() - start
            async with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["result"] = {
                    "article_url": result["article_url"],
                    "author": result["author"],
                    "authors": result.get("authors", []),
                    "status": result["status"],
                    "error": result.get("error"),
                    "elapsed_seconds": round(elapsed, 2),
                }
                _jobs[job_id]["elapsed_seconds"] = round(elapsed, 2)
                _jobs[job_id]["completed_at"] = time.monotonic()
            log.info("Job %s completed in %.1fs (status=%s)", job_id, elapsed, result["status"])
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            async with _jobs_lock:
                _jobs[job_id]["status"] = "timeout"
                _jobs[job_id]["error"] = f"Crawl exceeded maximum time of {CRAWL_TIMEOUT} seconds"
                _jobs[job_id]["elapsed_seconds"] = round(elapsed, 2)
                _jobs[job_id]["completed_at"] = time.monotonic()
            log.warning("Job %s timed out after %.1fs", job_id, elapsed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.exception("Job %s failed for %s", job_id, url)
            async with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = f"{type(exc).__name__}: {exc}"
                _jobs[job_id]["elapsed_seconds"] = round(elapsed, 2)
                _jobs[job_id]["completed_at"] = time.monotonic()


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check API health and version."""
    return HealthResponse(
        status="ok",
        version="0.3.0",
        max_concurrent=MAX_CONCURRENT,
    )


@app.post("/crawl", response_model=JobSubmitResponse, status_code=202, tags=["Crawl"])
async def submit_crawl(
    req: CrawlRequest,
    background_tasks: BackgroundTasks,
    _=Depends(verify_api_key),
):
    """Submit a crawl job. Returns immediately with a job_id for polling."""
    await _cleanup_expired_jobs()

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "url": str(req.url),
            "status": "processing",
            "created_at": now,
            "created_monotonic": time.monotonic(),
            "completed_at": None,
            "elapsed_seconds": None,
            "result": None,
            "error": None,
        }

    background_tasks.add_task(
        _run_crawl,
        job_id=job_id,
        url=str(req.url),
        timeout=req.timeout,
        delay=req.delay,
        use_playwright=req.use_playwright,
    )

    log.info("Submitted crawl job %s for %s", job_id, req.url)
    return JobSubmitResponse(
        job_id=job_id,
        status="processing",
        url=str(req.url),
        created_at=now,
    )


@app.get("/crawl/{job_id}", response_model=JobStatusResponse, tags=["Crawl"])
async def get_crawl_status(job_id: str, _=Depends(verify_api_key)):
    """Poll the status of a crawl job."""
    async with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    now = time.monotonic()
    elapsed = None
    if job["status"] == "processing":
        elapsed = round(now - job.get("created_monotonic", now), 1)

    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        url=job["url"],
        created_at=job["created_at"],
        elapsed_seconds=job.get("elapsed_seconds") or elapsed,
        result=CrawlResult(**job["result"]) if job.get("result") else None,
        error=job.get("error"),
    )


@app.post("/crawl/batch", response_model=BatchJobSubmitResponse, status_code=202, tags=["Crawl"])
async def submit_batch(
    req: BatchCrawlRequest,
    background_tasks: BackgroundTasks,
    _=Depends(verify_api_key),
):
    """Submit batch crawl jobs. Returns job_ids for polling."""
    if len(req.urls) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 URLs per batch")

    await _cleanup_expired_jobs()

    job_ids = []
    now = datetime.now(timezone.utc).isoformat()
    async with _jobs_lock:
        for url in req.urls:
            job_id = str(uuid.uuid4())
            _jobs[job_id] = {
                "job_id": job_id,
                "url": str(url),
                "status": "processing",
                "created_at": now,
                "created_monotonic": time.monotonic(),
                "completed_at": None,
                "elapsed_seconds": None,
                "result": None,
                "error": None,
            }
            job_ids.append(job_id)
            background_tasks.add_task(
                _run_crawl,
                job_id=job_id,
                url=str(url),
                timeout=req.timeout,
                delay=req.delay,
                use_playwright=req.use_playwright,
            )

    log.info("Submitted %d batch crawl jobs", len(job_ids))
    return BatchJobSubmitResponse(job_ids=job_ids, total=len(job_ids))
