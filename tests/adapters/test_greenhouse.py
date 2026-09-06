"""T023: fixture test for pipelines/adapters/greenhouse.py, modeled on
a recorded shape of Stripe's real boards-api response."""

from pipelines.adapters.greenhouse import fetch_postings

FIXTURE = {
    "jobs": [
        {
            "id": 7586413,
            "title": "Product Manager, Hardware",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=7586413",
            "location": {"name": "San Francisco, CA"},
            "departments": [{"name": "Product"}, {"name": "Hardware"}],
            "first_published": "2026-08-01T12:00:00-05:00",
            "content": "<p>Build the future of payments hardware. <a>Read more</a></p>",
        },
        {
            "id": 7586414,
            "title": "  Software Engineer, Backend  ",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=7586414",
            "location": None,
            "departments": [],
            "first_published": None,
            "content": None,
        },
    ]
}


def test_fetch_postings_maps_fields(mock_requests, make_employer):
    mock_requests.get(
        "boards-api.greenhouse.io/v1/boards/stripe/jobs", json_data=FIXTURE
    )
    employer = make_employer("greenhouse", {"token": "stripe"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 2
    first = postings[0]
    assert first["external_id"] == "7586413"
    assert first["title"] == "Product Manager, Hardware"
    assert first["source_url"] == "https://stripe.com/jobs/search?gh_jid=7586413"
    assert first["location_raw"] == "San Francisco, CA"
    assert first["department"] == "Product, Hardware"
    assert first["posted_date"] == "2026-08-01"
    assert "Read more" not in first["description_text"]


def test_fetch_postings_handles_missing_optional_fields(mock_requests, make_employer):
    mock_requests.get(
        "boards-api.greenhouse.io/v1/boards/stripe/jobs", json_data=FIXTURE
    )
    employer = make_employer("greenhouse", {"token": "stripe"})

    postings = list(fetch_postings(employer))

    second = postings[1]
    assert second["title"] == "Software Engineer, Backend"  # clean_text collapses whitespace
    assert second["location_raw"] is None
    assert second["department"] is None
    assert second["posted_date"] is None
    assert second["description_text"] is None


def test_fetch_postings_no_token_yields_nothing(mock_requests, make_employer):
    employer = make_employer("greenhouse", {})

    postings = list(fetch_postings(employer))

    assert postings == []
    assert mock_requests.calls == []
