"""Post-processing helpers for crawl results."""

from __future__ import annotations


def author_key(result: dict) -> str | None:
    """A stable identity for a result's author, or None when it has none.

    Profile URL is the strongest signal, then email, then the name on its own.
    """
    author = result.get("author") or {}
    if author.get("profile_url"):
        return str(author["profile_url"]).rstrip("/").lower()
    if author.get("email"):
        return str(author["email"]).lower()
    name = (author.get("name") or "").strip().lower()
    return name or None


def dedupe_results(results: list[dict]) -> list[dict]:
    """Collapse results to one entry per author, collecting every article URL.

    The first result for an author is kept and the others contribute any fields
    it is missing. Results with no identifiable author are left as separate
    rows: merging them would conflate unrelated pages.
    """
    deduped: list[dict] = []
    by_author: dict[str, dict] = {}

    for result in results:
        key = author_key(result)
        article_url = result.get("article_url")

        if key is None or key not in by_author:
            entry = dict(result)
            entry["article_urls"] = [article_url]
            deduped.append(entry)
            if key is not None:
                by_author[key] = entry
            continue

        existing = by_author[key]
        if article_url and article_url not in existing["article_urls"]:
            existing["article_urls"].append(article_url)
        _fill_missing(existing, result)

    return deduped


def _fill_missing(target: dict, source: dict) -> None:
    """Copy fields the kept entry lacks from a duplicate result."""
    target_author = target.setdefault("author", {})
    source_author = source.get("author") or {}
    for field, value in source_author.items():
        if field == "social_links":
            if value and not target_author.get("social_links"):
                target_author["social_links"] = value
            continue
        if value and not target_author.get(field):
            target_author[field] = value
