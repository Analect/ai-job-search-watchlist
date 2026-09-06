"""T027: fixture test for pipelines/adapters/pinpoint.py, modeled on a
recorded shape of a real postings.json response."""

from pipelines.adapters.pinpoint import fetch_postings

FIXTURE = {
    "data": [
        {
            "id": 42,
            "url": "https://cinven.pinpointhq.com/postings/abc",
            "title": "Investment Associate",
            "location": {"name": "London, UK"},
            "job": {"department": {"name": "Investments"}},
            "employment_type": "Full-time",
            "workplace_type": "remote",
            "deadline_at": "2026-09-30T00:00:00Z",
            "description": "Analyze deals.",
            "key_responsibilities": "Do diligence.",
            "key_responsibilities_header": "Responsibilities",
            "skills_knowledge_expertise": None,
            "benefits": "Great benefits.",
            "benefits_header": "Benefits",
        },
        {
            "id": 43,
            "url": None,  # missing url -> should be skipped
            "title": "Skipped Posting",
        },
        {
            "id": 44,
            "url": "https://cinven.pinpointhq.com/postings/def",
            "title": "Ops Analyst",
            "location": {"city": "Dublin", "province": "Leinster"},
        },
    ]
}


def test_fetch_postings_maps_fields_and_builds_description(mock_requests, make_employer):
    mock_requests.get("cinven.pinpointhq.com/postings.json", json_data=FIXTURE)
    employer = make_employer("pinpoint", {"slug": "cinven"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 2  # the url-less posting is skipped
    first = postings[0]
    assert first["external_id"] == "42"
    assert first["title"] == "Investment Associate"
    assert first["location_raw"] == "London, UK"
    assert first["department"] == "Investments"
    assert first["employment_type"] == "Full-time"
    assert first["is_remote"] is True
    assert first["posted_date"] == "2026-09-30"
    assert "Responsibilities" in first["description_text"]
    assert "Great benefits" in first["description_text"]

    second = postings[1]
    assert second["external_id"] == "44"
    assert second["location_raw"] == "Dublin, Leinster"  # falls back to city/province
    assert second["description_text"] is None


def test_fetch_postings_no_slug_yields_nothing(mock_requests, make_employer):
    employer = make_employer("pinpoint", {})
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []
