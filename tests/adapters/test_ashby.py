"""T025: fixture test for pipelines/adapters/ashby.py, modeled on a
recorded shape of OpenAI's real job-board API."""

from pipelines.adapters.ashby import fetch_postings

FIXTURE = {
    "jobs": [
        {
            "id": "job-1",
            "title": "Research Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/openai/job-1",
            "location": "San Francisco",
            "secondaryLocations": ["New York", {"location": "Remote"}],
            "address": {
                "postalAddress": {
                    "addressLocality": "San Francisco",
                    "addressRegion": "CA",
                    "addressCountry": "US",
                }
            },
            "isRemote": None,
            "workplaceType": "Remote",
            "employmentType": "FullTime",
            "department": "Research",
            "publishedAt": "2026-07-15T00:00:00.000Z",
            "descriptionHtml": "<p>Research the frontier.</p>",
            "descriptionPlain": "Research the frontier (plain).",
            "isListed": True,
        },
        {
            "id": "job-2",
            "title": "Unlisted Draft Role",
            "isListed": False,
        },
    ]
}


def test_fetch_postings_maps_fields(mock_requests, make_employer):
    mock_requests.get("api.ashbyhq.com/posting-api/job-board/openai", json_data=FIXTURE)
    employer = make_employer("ashby", {"token": "openai"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 1  # the unlisted draft is filtered out
    posting = postings[0]
    assert posting["external_id"] == "job-1"
    assert posting["title"] == "Research Engineer"
    assert posting["location_raw"] == "San Francisco, New York, Remote"
    assert posting["location_city"] == "San Francisco"
    assert posting["location_region"] == "CA"
    assert posting["location_country"] == "US"
    assert posting["is_remote"] is True  # workplaceType fallback since isRemote is None
    assert posting["employment_type"] == "FullTime"
    assert posting["department"] == "Research"
    assert posting["posted_date"] == "2026-07-15"
    assert posting["description_text"] == "<p>Research the frontier.</p>"  # HTML preferred


def test_fetch_postings_no_token_yields_nothing(mock_requests, make_employer):
    employer = make_employer("ashby", {})
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []
