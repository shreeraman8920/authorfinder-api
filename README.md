# AuthorFinder

A small Python web crawler that extracts journalist/author contact information
from a news article URL.

Given a news article URL, it:

1. Fetches the article page (with `requests`/BeautifulSoup; falls back to a
   headless browser via Playwright when the page needs JavaScript rendering).
2. Identifies the article's author.
3. Locates the author's profile page **on the same news website**.
4. Fetches the author page and extracts all publicly listed author information.

It never guesses or fabricates contact information: every field returned is
something that is actually present on the fetched pages, and it only ever
requests two pages (the article and the author's profile page).

## Extracted fields

For each article it produces JSON shaped like:

```json
{
  "article_url": "https://news.example.com/2026/01/15/some-story",
  "author": {
    "name": "Jane Doe",
    "profile_url": "https://news.example.com/author/jane-doe/",
    "job_title": "Senior Reporter",
    "bio": "Jane Doe covers climate policy for Example News...",
    "email": "jane.doe@example.com",
    "linkedin": "https://www.linkedin.com/in/jane-doe",
    "twitter": "https://twitter.com/janedoe",
    "social_links": [
      {"platform": "linkedin", "url": "https://www.linkedin.com/in/jane-doe"},
      {"platform": "twitter", "url": "https://twitter.com/janedoe"}
    ],
    "organization": "Example News",
    "location": "Washington, D.C."
  },
  "status": "success"
}
```

* `status` is one of `success`, `no_author_found`, `no_author_page`, `blocked`,
  or `error`.
* Missing fields are returned as `null` (or `[]` for `social_links`) — the
  crawler does **not** infer data that is not publicly present.
* If an author page cannot be found, `status` reports that instead of guessing.

## How author detection works

The crawler adapts to different news sites rather than hard-coding one layout:

* **JSON-LD** (`NewsArticle.author` → `Person`) for name, `url`, and `sameAs`.
* **Meta tags**: `author`, `byl`, `byline`, `article:author`, `parsely-author`,
  `dc.creator`, `citation_author`, and related.
* **Byline markup**: `a[rel=author]`, `.byline a`, `.author a`,
  `[class*=byline] a`, `[class*=author] a`, and similar.
* **Author/profile URL patterns** anywhere on the page, e.g. paths containing
  `/author/`, `/authors/`, `/contributor/`, `/profile/`, `/staff/`,
  `/reporter/`, and author subdomains like `author.example.com`.
* **Title fallback** for a `By <name>` pattern, used only when nothing else is
  found.

Candidate scoring prefers a named author whose profile URL is on the same
domain and matches an author-page pattern. External URLs (for example a
publisher's Facebook page in `article:author`) are **not** treated as the
site's author page.

## How extraction works

On the author page, information is gathered from visible content **and** from
HTML attributes/structured data:

* `mailto:` links and email-like text (including common `name [at] domain
  [dot] com` obfuscation). Addresses are deduplicated and obviously fake /
  placeholder addresses (e.g. `user@example.com`, `logo@2x.png`) are dropped.
* Social links from anchor `href`s **and** JSON-LD `sameAs`, deduplicated and
  classified (linkedin, twitter/x, facebook, instagram, youtube, threads,
  mastodon, bluesky, github, tiktok, etc.). Scanning is limited to the page's
  main/author region so the site's own footer social accounts are not mistaken
  for the author's.
* Bio from JSON-LD `description` (HTML tags are stripped), `meta` description,
  or bio paragraphs.
* Job title, organization, and location from JSON-LD (`jobTitle`, `worksFor`,
  `address`) or common visible markup (`meta og:site_name`, `.author-role`,
  `.author-location`, etc.).

## Requirements

* Python 3.9+
* `requests`, `beautifulsoup4` (used for static HTML)
* `playwright` (optional, only needed for JavaScript-rendered pages)

## Installation

```bash
# From the project root
pip install -e .
```

For JavaScript-rendered pages you also need the Playwright browser:

```bash
pip install -e ".[playwright]"
python -m playwright install chromium
```

## Usage

```bash
authorfinder "https://www.theguardian.com/..." 
```

Options:

| Flag | Description |
| --- | --- |
| `--no-js` | Disable the Playwright (JavaScript rendering) fallback. |
| `--timeout SECONDS` | Per-request timeout (default `15`). |
| `--delay SECONDS` | Delay between requests, to be polite (default `1`). |
| `--user-agent UA` | Override the crawler's User-Agent. |
| `--output FILE, -o FILE` | Write the JSON to a file instead of stdout. |
| `--verbose, -v` | Enable debug logging. |
| `--version` | Print the version. |

Multiple URLs can be passed; the output is then wrapped in `{"results": [...]}`.

Example:

```bash
authorfinder -v -o result.json \
  "https://news.example.com/story-1" \
  "https://news.example.com/story-2"
```

You can also use it as a library:

```python
from authorfinder.crawler import AuthorCrawler

crawler = AuthorCrawler(delay=1.5, timeout=25)
result = crawler.crawl("https://www.theguardian.com/...")
print(result["status"], result["author"]["name"])
```

## Configuration / ethics

* **robots.txt is respected** for every request (checked per origin).
* The crawler fetches **only** the article page and the relevant author page —
  never the whole site.
* Requests are rate-limited via `--delay` and bounded by `--timeout`.
* Transient failures (429/5xx, connection errors) are retried a few times with
  backoff, honouring `Retry-After`, before the crawl gives up.
* Pages that need JavaScript are rendered via Playwright, and cookie/consent
  banners are dismissed, so the content a reader would see is what gets read.
* It cannot and will not bypass paywalls or login walls. A browser is used only
  to render pages the publisher serves to browsers — never to defeat bot
  protection; when a protection still refuses, the crawl is reported as
  `blocked` rather than worked around.

## Project layout

```
src/authorfinder/
  cli.py        # command-line entry point
  crawler.py    # orchestration: article -> author -> author page -> extraction
  fetch.py      # requests/Playwright fetching + robots.txt handling
  author.py     # author detection on the article page
  extract.py    # info extraction from the author page (email, social, bio, ...)
  urls.py       # URL resolution, cleaning, author-page & social detection
tests/          # pytest suite (no network access required)
```

## Tests

```bash
python -m pytest
```

The test suite covers URL resolution, author-page detection, author candidate
selection, email extraction, social-link extraction, bio extraction, and the
full crawl pipeline (using canned HTML fixtures — no network needed).

## Status values

| Status | Meaning |
| --- | --- |
| `success` | Author found and author-page information extracted. |
| `no_author_found` | No author could be identified on the article page. |
| `no_author_page` | An author was identified but no same-site profile URL exists. |
| `blocked` | The site refused the fetch — robots.txt, a 401/403/451 refusal, persistent rate limiting, or a bot-protection challenge. |
| `paywall` | The content is behind a paywall or registration wall and cannot be accessed. |
| `error` | Fetch/extract failed for another reason (details in `error`). |