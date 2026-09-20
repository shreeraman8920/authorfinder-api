"""Orchestrator: article -> author detection -> author page -> extraction."""

from __future__ import annotations

import logging

from .author import choose_author, detect_authors, choose_multiple_authors
from .extract import extract_author_page
from .fetch import BlockedError, Fetcher, PaywallError, parse_html
from .urls import normalize_article_url, same_domain

log = logging.getLogger(__name__)


class AuthorCrawler:
    def __init__(self, fetcher: Fetcher | None = None, **fetch_kwargs):
        self.fetcher = fetcher or Fetcher(**fetch_kwargs)

    async def crawl(self, article_url: str) -> dict:
        article_url = normalize_article_url(article_url)
        result: dict = {
            "article_url": article_url,
            "author": {
                "name": None,
                "profile_url": None,
                "job_title": None,
                "bio": None,
                "email": None,
                "linkedin": None,
                "twitter": None,
                "social_links": [],
                "organization": None,
                "location": None,
            },
            "authors": [],
            "status": "error",
        }
        try:
            log.info("Stage 1/4: Fetching article page: %s", article_url)
            article_res = await self.fetcher.fetch(article_url)
            article_soup = parse_html(article_res.html)
            final_article_url = article_res.final_url or article_url
            result["article_url"] = final_article_url

            log.info("Stage 2/4: Detecting author on article page")
            candidates = detect_authors(article_soup, final_article_url)
            if not candidates:
                log.warning("No author found on article page")
                result["status"] = "no_author_found"
                return result

            author = choose_author(candidates, final_article_url)
            log.info(
                "Detected author candidate: name=%r profile_url=%r (from %d candidates)",
                author.name,
                author.profile_url,
                len(candidates),
            )
            if author.name:
                result["author"]["name"] = author.name

            if not author.profile_url:
                log.warning("Author page URL not available for %r", author.name)
                result["status"] = "no_author_page"
                return result
            if not same_domain(author.profile_url, final_article_url):
                log.warning("Detected profile URL is not on the article's site: %s", author.profile_url)
                result["status"] = "no_author_page"
                return result

            result["author"]["profile_url"] = author.profile_url
            log.info("Stage 3/4: Fetching author page: %s", author.profile_url)
            author_res = await self.fetcher.fetch(author.profile_url)
            author_soup = parse_html(author_res.html)
            author_final_url = author_res.final_url or author.profile_url
            result["author"]["profile_url"] = author_final_url

            log.info("Stage 4/4: Extracting author information")
            info = extract_author_page(author_soup, author_final_url)
            for key in ("job_title", "bio", "email", "linkedin", "twitter", "social_links", "organization", "location"):
                value = info.get(key)
                if value:
                    result["author"][key] = value
            if not result["author"]["name"]:
                result["author"]["name"] = info.get("name")

            multiple = choose_multiple_authors(candidates, final_article_url)
            if len(multiple) > 1:
                result["authors"] = [result["author"]]
                for extra in multiple[1:]:
                    if extra.profile_url and same_domain(extra.profile_url, final_article_url):
                        try:
                            er = await self.fetcher.fetch(extra.profile_url)
                            esoup = parse_html(er.html)
                            einfo = extract_author_page(esoup, er.final_url or extra.profile_url)
                            eauthor = {
                                "name": einfo.get("name") or extra.name,
                                "profile_url": er.final_url or extra.profile_url,
                                "job_title": einfo.get("job_title"),
                                "bio": einfo.get("bio"),
                                "email": einfo.get("email"),
                                "linkedin": einfo.get("linkedin"),
                                "twitter": einfo.get("twitter"),
                                "social_links": einfo.get("social_links", []),
                                "organization": einfo.get("organization"),
                                "location": einfo.get("location"),
                            }
                            result["authors"].append(eauthor)
                        except Exception:
                            result["authors"].append({
                                "name": extra.name,
                                "profile_url": extra.profile_url,
                            })
                    else:
                        result["authors"].append({
                            "name": extra.name,
                            "profile_url": extra.profile_url,
                        })

            result["status"] = "success"
        except BlockedError as exc:
            log.warning("Crawl blocked by the site: %s", exc)
            result["status"] = "blocked"
            result["error"] = str(exc)
        except PaywallError as exc:
            log.warning("Content behind paywall: %s", exc)
            result["status"] = "paywall"
            result["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - report any failure gracefully
            log.exception("Crawl of %s failed", article_url)
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result