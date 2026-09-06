"""T026: fixture test for pipelines/adapters/workable.py, modeled on a
recorded shape of Hugging Face's real v3 jobs API + detail fetch."""

from pipelines.adapters.workable import fetch_postings

LIST_FIXTURE = {
    "results": [
        {
            "id": 999,
            "shortcode": "ABC123",
            "title": "ML Engineer",
            "location": {"city": "Paris", "region": "Ile-de-France", "country": "France"},
            "remote": True,
            "type": "full",
            "department": ["Engineering", "ML"],
            "published": "2026-06-01T00:00:00.000Z",
        },
        {
            "id": 1000,
            "shortcode": "DEF456",
            "title": "Support Engineer",
            "location": {},
            "remote": False,
            "type": "full",
            "department": [],
            "published": None,
        },
    ]
}


def test_fetch_postings_maps_fields_and_fetches_description(mock_requests, make_employer):
    mock_requests.post(
        "apply.workable.com/api/v3/accounts/huggingface/jobs", json_data=LIST_FIXTURE
    )
    mock_requests.get(
        "apply.workable.com/api/v1/accounts/huggingface/jobs/ABC123",
        json_data={"description": "<p>Train models.</p>"},
    )
    mock_requests.get(
        "apply.workable.com/api/v1/accounts/huggingface/jobs/DEF456",
        status_code=404,
    )
    employer = make_employer("workable", {"token": "huggingface"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 2
    first = postings[0]
    assert first["external_id"] == "999"
    assert first["title"] == "ML Engineer"
    assert first["source_url"] == "https://apply.workable.com/huggingface/j/ABC123/"
    assert first["location_city"] == "Paris"
    assert first["location_raw"] == "Paris, Ile-de-France, France"
    assert first["is_remote"] is True
    assert first["department"] == "Engineering, ML"
    assert first["posted_date"] == "2026-06-01"
    assert first["description_text"] == "<p>Train models.</p>"

    second = postings[1]
    # detail fetch 404s — best-effort, must not fail the whole posting
    assert second["description_text"] is None
    assert second["department"] is None
    assert second["location_city"] is None


def test_fetch_postings_no_token_yields_nothing(mock_requests, make_employer):
    employer = make_employer("workable", {})
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []
