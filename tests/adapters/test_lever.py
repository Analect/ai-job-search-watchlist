"""T024: fixture test for pipelines/adapters/lever.py, modeled on a
recorded shape of Anyscale's real postings API."""

from pipelines.adapters.lever import fetch_postings

PAGE_1 = [
    {
        "id": "abc-123",
        "text": "Senior Software Engineer",
        "hostedUrl": "https://jobs.lever.co/anyscale/abc-123",
        "categories": {
            "allLocations": ["San Francisco", "Remote"],
            "commitment": "Full-time",
            "department": "Engineering",
        },
        "workplaceType": "remote",
        "createdAt": 1735689600000,
        "description": "Build Ray.",
        "lists": [{"text": "Requirements", "content": "<li>5+ years Python</li>"}],
        "additional": "We are an EEO employer.",
    },
    {
        "id": "def-456",
        "text": "Recruiter (no hosted url, should be skipped)",
        "hostedUrl": None,
    },
]


def test_fetch_postings_maps_fields_and_builds_description(mock_requests, make_employer):
    mock_requests.get("api.lever.co/v0/postings/anyscale", json_data=PAGE_1)
    employer = make_employer("lever", {"token": "anyscale"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 1  # the no-hostedUrl posting is skipped
    posting = postings[0]
    assert posting["external_id"] == "abc-123"
    assert posting["title"] == "Senior Software Engineer"
    assert posting["location_raw"] == "San Francisco, Remote"
    assert posting["employment_type"] == "Full-time"
    assert posting["department"] == "Engineering"
    assert posting["is_remote"] is True
    assert posting["posted_date"] == "2025-01-01"
    assert "Requirements" in posting["description_text"]
    assert "EEO employer" in posting["description_text"]


def test_fetch_postings_paginates_by_skip(mock_requests, make_employer):
    full_page = [
        {
            "id": f"job-{i}",
            "text": f"Role {i}",
            "hostedUrl": f"https://jobs.lever.co/anyscale/job-{i}",
            "categories": {},
        }
        for i in range(100)
    ]
    second_page = [
        {
            "id": "job-100",
            "text": "Role 100",
            "hostedUrl": "https://jobs.lever.co/anyscale/job-100",
            "categories": {},
        }
    ]

    mock_requests.get("skip=0", json_data=full_page)
    mock_requests.get("skip=100", json_data=second_page)

    employer = make_employer("lever", {"token": "anyscale"})
    postings = list(fetch_postings(employer))

    assert len(postings) == 101


def test_fetch_postings_no_token_yields_nothing(mock_requests, make_employer):
    employer = make_employer("lever", {})
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []
