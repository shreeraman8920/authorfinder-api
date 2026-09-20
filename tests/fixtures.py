"""HTML fixtures used by the test suite (no network access needed)."""

ARTICLE_URL = "https://news.example.com/2024/01/15/climate-policy-report"

AUTHOR_URL = "https://news.example.com/author/jane-doe/"


def article_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Climate Policy Report - By Jane Doe | Example News</title>
  <meta name="author" content="Jane Doe">
  <meta name="description" content="A report on climate policy.">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": "Climate Policy Report",
    "url": "{ARTICLE_URL}",
    "author": {{
      "@type": "Person",
      "name": "Jane Doe",
      "url": "{AUTHOR_URL}",
      "sameAs": ["https://twitter.com/janedoe", "https://www.linkedin.com/in/jane-doe"]
    }},
    "publisher": {{"@type": "Organization", "name": "Example News"}}
  }}
  </script>
</head>
<body>
  <article>
    <h1>Climate Policy Report</h1>
    <div class="byline">
      By <a rel="author" href="/author/jane-doe/">Jane Doe</a>
    </div>
    <p>The full text of the article goes here.</p>
    <a href="/author/jane-doe/">More from this author</a>
    <a href="?utm_source=twitter&utm_medium=social&x=1">Share</a>
  </article>
</body>
</html>
"""


def author_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Jane Doe | Example News</title>
  <meta property="og:site_name" content="Example News">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Person",
    "name": "Jane Doe",
    "url": "https://news.example.com/author/jane-doe/",
    "jobTitle": "Senior Reporter",
    "description": "Jane Doe covers climate policy for Example News, focusing on regulation and environmental justice. She has written for the outlet since 2019.",
    "email": "jane.doe@newsexample.com",
    "worksFor": {"@type": "Organization", "name": "Example News"},
    "address": {"@type": "PostalAddress", "addressLocality": "Washington, D.C."},
    "sameAs": ["https://www.linkedin.com/in/jane-doe", "https://twitter.com/janedoe"]
  }
  </script>
</head>
<body>
  <main>
  <header class="author">
    <h1>Jane Doe</h1>
    <p class="author-role">Senior Reporter</p>
    <p class="author-location">Washington, D.C.</p>
  </header>
  <div class="author-bio">
    Jane Doe covers climate policy for Example News, focusing on regulation and
    environmental justice. She has written for the outlet since 2019.
  </div>
  <p>Contact: <a href="mailto:jane.doe@newsexample.com">jane.doe@newsexample.com</a></p>
  <ul class="social">
    <li><a href="https://www.linkedin.com/in/jane-doe">LinkedIn</a></li>
    <li><a href="https://twitter.com/janedoe">Twitter</a></li>
  </ul>
  <p class="bio">A longer standalone bio paragraph that also describes Jane's work in more depth across the site.</p>
  </main>
  <footer>
    <a href="https://www.facebook.com/example-news">Follow Example News on Facebook</a>
    <a href="https://www.instagram.com/example_news">Follow Example News on Instagram</a>
  </footer>
</body>
</html>
"""


def author_html_no_contact() -> str:
    return """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Jane Doe | Example News</title></head>
<body>
  <h1>Jane Doe</h1>
  <div class="author-bio">Jane Doe writes for Example News.</div>
</body>
</html>
"""