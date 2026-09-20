from authorfinder.extract import (
    extract_author_page,
    extract_emails,
    extract_social_links,
    extract_json_ld,
    iter_ld_persons,
)
from authorfinder.fetch import parse_html

from .fixtures import AUTHOR_URL, article_html, author_html, author_html_no_contact


def test_extract_emails_from_mailto():
    html = '<a href="mailto:a@newsexample.com">a@newsexample.com</a> <a href="mailto:a@newsexample.com">x</a>'
    assert extract_emails(parse_html(html)) == ["a@newsexample.com"]


def test_extract_emails_from_text_and_dedupe():
    html = "<p>Reach me at first.last@newsexample.com or first.last@newsexample.com again.</p>"
    assert extract_emails(parse_html(html)) == ["first.last@newsexample.com"]


def test_extract_emails_obfuscated():
    html = "<p>Email: jane [at] newsexample [dot] com</p>"
    assert extract_emails(parse_html(html)) == ["jane@newsexample.com"]


def test_extract_emails_filters_artifacts():
    html = '<img src="logo@2x.png"><p>some@example.com/image.png</p>'
    assert extract_emails(parse_html(html)) == []


def test_extract_social_links_dedupe():
    html = """
      <a href="https://www.linkedin.com/in/jane-doe">in</a>
      <a href="https://twitter.com/janedoe">tw</a>
      <a href="https://x.com/janedoe">x</a>
      <a href="https://news.example.com/author/jane-doe/">profile</a>
    """
    socials = extract_social_links(parse_html(html), "https://news.example.com/author/jane-doe/")
    by_platform = {s["platform"]: s["url"] for s in socials}
    assert by_platform["linkedin"] == "https://www.linkedin.com/in/jane-doe"
    assert by_platform["twitter"] == "https://twitter.com/janedoe"
    assert len(socials) == 2


def test_extract_json_ld_and_person():
    soup = parse_html(author_html())
    blocks = extract_json_ld(soup)
    persons = list(iter_ld_persons(blocks))
    assert persons and persons[0]["name"] == "Jane Doe"


def test_extract_author_page_full():
    result = extract_author_page(parse_html(author_html()), AUTHOR_URL)
    assert result["name"] == "Jane Doe"
    assert result["profile_url"] == AUTHOR_URL
    assert result["job_title"] == "Senior Reporter"
    assert result["email"] == "jane.doe@newsexample.com"
    assert result["linkedin"] == "https://www.linkedin.com/in/jane-doe"
    assert result["twitter"] == "https://twitter.com/janedoe"
    assert result["organization"] == "Example News"
    assert result["location"] == "Washington, D.C."
    assert "climate policy" in result["bio"].lower()
    platforms = {s["platform"] for s in result["social_links"]}
    assert platforms == {"linkedin", "twitter"}
    urls = {s["url"] for s in result["social_links"]}
    assert all("facebook.com" not in u and "instagram.com" not in u for u in urls)


def test_extract_author_page_missing_fields_are_null():
    result = extract_author_page(parse_html(author_html_no_contact()), "https://news.example.com/author/jane-doe/")
    assert result["name"] == "Jane Doe"
    assert result["email"] is None
    assert result["linkedin"] is None
    assert result["twitter"] is None
    assert result["social_links"] == []
    assert result["organization"] is None


def test_article_json_ld_author_url_is_resolved():
    from authorfinder.author import detect_authors

    candidates = detect_authors(parse_html(article_html()), "https://news.example.com/2024/01/15/climate-policy-report")
    assert any(c.profile_url == AUTHOR_URL for c in candidates)


def test_bio_strips_html_tags():
    html = """<html><head>
      <script type="application/ld+json">{
        "@type": "Person",
        "name": "Jane Doe",
        "description": "<p>Jane writes about policy</p><p>for Example News.</p>"
      }</script>
    </head><body><main><h1>Jane Doe</h1></main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/author/jane-doe/")
    assert result["bio"] == "Jane writes about policy for Example News."
    assert "<p>" not in result["bio"]


def test_social_links_exclude_footer_site_accounts():
    html = """<html><body>
      <main>
        <h1>Jane Doe</h1>
        <a href="https://twitter.com/janedoe">Twitter</a>
      </main>
      <footer>
        <a href="https://www.facebook.com/sitenews">Facebook</a>
        <a href="https://www.instagram.com/sitenews">Instagram</a>
      </footer>
    </body></html>"""
    socials = extract_social_links(parse_html(html), "https://news.example.com/author/jane-doe/", container=_main(html))
    by_platform = {s["platform"]: s["url"] for s in socials}
    assert by_platform == {"twitter": "https://twitter.com/janedoe"}


def test_social_links_ignores_body_level_author_classes():
    # WordPress puts author classes on <body>; the whole page must not be
    # treated as an author container (site footer accounts would leak in).
    html = """<html><body class="author author-ed-silverman wp-theme-stat">
      <nav class="author-social">
        <a href="https://x.com/Pharmalot">@Pharmalot</a>
      </nav>
      <footer>
        <a href="https://www.facebook.com/statnews/"></a>
        <a href="https://www.instagram.com/statnews/"></a>
      </footer>
    </body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/staff/ed-silverman/")
    by_platform = {s["platform"]: s["url"] for s in result["social_links"]}
    assert by_platform == {"twitter": "https://x.com/Pharmalot"}


def test_decode_cf_email():
    from authorfinder.extract import _decode_cf_email
    # adam.feuerstein@statnews.com encoded with Cloudflare
    assert _decode_cf_email("b0d1d4d1dd9ed6d5c5d5c2c3c4d5d9def0c3c4d1c4ded5c7c39ed3dfdd") == "adam.feuerstein@statnews.com"
    # jane@example.com (key=0xc1)
    assert _decode_cf_email("c1aba0afa481a4b9a0acb1ada4efa2aeac") == "jane@example.com"


def test_email_from_cloudflare_cfemail():
    html = """<html><body>
      <main>
        <div class="author-socials">
          <a class="social-item-icon email" data-cfemail="b0d1d4d1dd9ed6d5c5d5c2c3c4d5d9def0c3c4d1c4ded5c7c39ed3dfdd"></a>
        </div>
      </main>
    </body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/staff/adam-feuerstein/")
    assert result["email"] == "adam.feuerstein@statnews.com"


def test_email_not_taken_from_organization_or_footer():
    html = """<html><head>
      <script type="application/ld+json">{
        "@type": "Organization",
        "name": "STAT",
        "email": "subscribers@statnews.com",
        "telephone": "(617) 929-2000"
      }</script>
    </head><body>
      <main>
        <div class="author-bio">Adam Feuerstein is a senior writer and biotech columnist for STAT.</div>
      </main>
      <footer>
        <a href="mailto:contact@statnews.com">Contact us</a>
      </footer>
    </body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/staff/adam-feuerstein/")
    assert result["email"] is None


def test_email_from_author_region_mailto():
    html = """<html><body>
      <main>
        <div class="author-socials">
          <a href="mailto:adam.feuerstein@statnews.com">Email Adam</a>
        </div>
      </main>
    </body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/staff/adam-feuerstein/")
    assert result["email"] == "adam.feuerstein@statnews.com"


def test_email_from_person_json_ld():
    html = """<html><head>
      <script type="application/ld+json">{
        "@type": "Person",
        "name": "Adam Feuerstein",
        "email": "adam.feuerstein@statnews.com"
      }</script>
    </head><body><main><h1>Adam Feuerstein</h1></main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/staff/adam-feuerstein/")
    assert result["email"] == "adam.feuerstein@statnews.com"


def _main(html: str):
    return parse_html(html).find("main")


def test_social_links_scoped_to_author_container_not_site_bar():
    html = """<html><body>
      <main>
        <div class="social">  <!-- site brand-bar accounts -->
          <a href="https://twitter.com/fiercepharma"></a>
          <a href="https://www.linkedin.com/showcase/fierce-pharma/"></a>
        </div>
        <div class="author-socials">  <!-- the author's own accounts -->
          <a href="https://twitter.com/KDunleavy"></a>
        </div>
      </main>
    </body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/person/kevin")
    by_platform = {s["platform"]: s["url"] for s in result["social_links"]}
    assert by_platform == {"twitter": "https://twitter.com/KDunleavy"}


def test_bio_fallback_skips_article_listings():
    # An author page often lists their stories; those excerpts are link-heavy
    # list items and must not be mistaken for the bio.
    html = """<html><body><main>
      <h1>Jane Doe</h1>
      <p>Jane Doe covers climate policy for Example News and writes about regulation, energy markets and environmental justice.</p>
      <ul>
        <li><p><a href="/story-1">A very long article headline about climate policy that a reader might click through to read the entire story</a></p></li>
      </ul>
    </main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/author/jane-doe/")
    assert result["bio"].startswith("Jane Doe covers climate policy")
    assert "click through" not in result["bio"]


def test_name_h1_is_not_used_when_it_is_the_site_name():
    html = """<html><head>
      <meta property="og:site_name" content="Example News">
      <meta name="author" content="Jane Doe">
    </head><body><main><h1>Example News</h1></main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/author/jane-doe/")
    assert result["name"] == "Jane Doe"


def test_email_prefers_author_address_over_shared_mailbox():
    html = """<html><body><main>
      <h1>Jane Doe</h1>
      <div class="author-bio">
        Jane Doe covers climate policy for Example News. Desk: webmaster@news.example.com.
        Jane can be reached at jane.doe@news.example.com.
      </div>
    </main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/author/jane-doe/")
    assert result["email"] == "jane.doe@news.example.com"


def test_social_links_from_json_ld_sameas_only_person():
    html = """<html><head>
      <script type="application/ld+json">{
        "@type": "Person",
        "name": "Jane Doe",
        "sameAs": ["https://twitter.com/janedoe", "https://www.linkedin.com/in/jane-doe"]
      }</script>
    </head><body><main><h1>Jane Doe</h1></main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/author/jane-doe/")
    by_platform = {s["platform"]: s["url"] for s in result["social_links"]}
    assert by_platform["twitter"] == "https://twitter.com/janedoe"
    assert by_platform["linkedin"] == "https://www.linkedin.com/in/jane-doe"


def test_social_link_inside_bio_prose_is_not_an_account():
    # A social URL mentioned inside the bio is a citation (an organisation the
    # author writes about), not one of the author's own accounts.
    html = """<html><body><main>
      <div class="author-bio">
        <p>Lauren Chan is a registered dietitian and an AAAS fellow. She is a member of
        <a href="https://www.youtube.com/c/dietitiansinnutritionsupport">Dietitians in Nutrition Support</a>
        and writes about nutrition for the publication every week.</p>
      </div>
      <nav class="author-social"><ul>
        <li><a href="https://x.com/Pharmalot">@Pharmalot</a></li>
      </ul></nav>
    </main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/staff/lauren-chan/")
    by_platform = {s["platform"]: s["url"] for s in result["social_links"]}
    assert "youtube" not in by_platform
    assert by_platform == {"twitter": "https://x.com/Pharmalot"}


def test_job_title_derived_from_bio_possessive():
    html = """<html><body><main>
      <div class="author-bio">Rafael Nam is NPR's Senior Business Editor.</div>
    </main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/people/rafael-nam")
    assert result["job_title"] == "Senior Business Editor"


def test_job_title_derived_from_bio_article_form():
    html = """<html><body><main>
      <div class="author-bio">Zoey Becker is a staff writer for Fierce Pharma Marketing.</div>
    </main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/person/zoey-becker")
    assert result["job_title"] == "staff writer"


def test_job_title_not_derived_from_an_unrelated_sentence():
    # The bio does not open by talking about this person, so an "is a ..."
    # sentence describes the publication, not the author.
    html = """<html><body><main>
      <h1>Jane Doe</h1>
      <div class="author-bio">The Guardian is a British daily newspaper known for its
      investigative journalism and its wide international coverage.</div>
    </main></body></html>"""
    result = extract_author_page(parse_html(html), "https://news.example.com/person/jane-doe")
    assert result["job_title"] is None