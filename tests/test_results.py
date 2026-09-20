from authorfinder.results import author_key, dedupe_results


def _result(url, name, profile=None, email=None, **author_extra):
    author = {"name": name, "profile_url": profile, "email": email, "social_links": []}
    author.update(author_extra)
    return {"article_url": url, "author": author, "status": "success"}


def test_author_key_prefers_profile_then_email_then_name():
    assert author_key(_result("u", "Jane Doe", "https://s.com/author/jane/")) == "https://s.com/author/jane"
    assert author_key(_result("u", "Jane Doe", email="jane@site.com")) == "jane@site.com"
    assert author_key(_result("u", "Jane Doe")) == "jane doe"
    assert author_key({"article_url": "u", "author": {}}) is None


def test_dedupe_collapses_one_author_across_articles():
    results = [
        _result("https://s.com/1", "Angus Liu", "https://s.com/person/angus-liu"),
        _result("https://s.com/2", "Angus Liu", "https://s.com/person/angus-liu"),
        _result("https://s.com/3", "Angus Liu", "https://s.com/person/angus-liu/"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1
    assert out[0]["article_url"] == "https://s.com/1"
    assert out[0]["article_urls"] == [
        "https://s.com/1",
        "https://s.com/2",
        "https://s.com/3",
    ]


def test_dedupe_keeps_distinct_authors_and_unauthored_rows_separate():
    results = [
        _result("https://s.com/1", "Angus Liu", "https://s.com/person/angus-liu"),
        _result("https://s.com/2", "Zoey Becker", "https://s.com/person/zoey-becker"),
        {"article_url": "https://s.com/3", "author": {}, "status": "blocked"},
        {"article_url": "https://s.com/4", "author": {}, "status": "blocked"},
    ]
    out = dedupe_results(results)
    assert len(out) == 4


def test_dedupe_fills_missing_fields_from_a_duplicate():
    first = _result("https://s.com/1", "Jane Doe", "https://s.com/author/jane")
    second = _result(
        "https://s.com/2",
        "Jane Doe",
        "https://s.com/author/jane",
        email="jane@site.com",
        job_title="Reporter",
    )
    out = dedupe_results([first, second])
    assert len(out) == 1
    assert out[0]["author"]["email"] == "jane@site.com"
    assert out[0]["author"]["job_title"] == "Reporter"


def test_dedupe_does_not_mutate_the_input_results():
    results = [_result("https://s.com/1", "Jane Doe", "https://s.com/author/jane")]
    dedupe_results(results)
    assert "article_urls" not in results[0]
