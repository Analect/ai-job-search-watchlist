"""T029: fixture test for pipelines/adapters/workday.py.

Uses the same requests.Session.send mock as every other adapter — dlt's
RESTClient (used for the paginated list call) also runs on a
requests.Session under the hood, so the same mocking strategy covers
both the plain fetch_json_with_retry probe calls and dlt's pagination.

The probe (`limit=1`, checking facets/total) and the real paginated
fetch (`limit=20`) both hit the exact same URL — a body-inspecting
responder distinguishes them, since URL-only matching can't.
"""

import json as json_module

from pipelines.adapters.workday import fetch_postings
from tests.adapters.conftest import FakeResponse

LIST_PATH = "/wday/cxs/acme/careers/jobs"
BASE_URL = "https://acme.wd5.myworkdayjobs.com"


def _by_body(probe_response, page_response):
    def handler(request):
        body = json_module.loads(request.body) if request.body else {}
        data = probe_response if body.get("limit") == 1 else page_response
        return FakeResponse(200, json_data=data)

    return handler


def _probe_with_locations_facet():
    return {
        "total": 1,
        "facets": [
            {
                "facetParameter": "locations",
                "values": [
                    {
                        "id": "london-office-id",
                        "descriptor": "London, Luke Street (Eagle Lab)",
                        "count": 1,
                    },
                    {"id": "ny-id", "descriptor": "New York, HQ", "count": 500},
                ],
            }
        ],
    }


def test_fetch_postings_filters_by_locations_facet(mock_requests, make_employer):
    page_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Software Engineer",
                "externalPath": "/job/London/Software-Engineer_R-001",
                "bulletFields": ["R-001"],
                "locationsText": "London, Luke Street (Eagle Lab)",
            }
        ],
    }
    mock_requests.register(
        "POST",
        f"acme.wd5.myworkdayjobs.com{LIST_PATH}",
        _by_body(_probe_with_locations_facet(), page_response),
    )
    mock_requests.get(
        "acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/London/Software-Engineer_R-001",
        json_data={
            "jobPostingInfo": {
                "jobDescription": "<p>Build things.</p>",
                "location": "London, Luke Street (Eagle Lab)",
                "timeType": "Full time",
                "startDate": "2026-07-01",
            }
        },
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    posting = postings[0]
    assert posting["external_id"] == "R-001"
    assert posting["title"] == "Software Engineer"
    assert posting["source_url"] == f"{BASE_URL}/careers/job/London/Software-Engineer_R-001"
    assert posting["location_raw"] == "London, Luke Street (Eagle Lab)"
    assert posting["employment_type"] == "Full time"
    assert posting["posted_date"] == "2026-07-01"
    assert posting["description_text"] == "<p>Build things.</p>"


def test_fetch_postings_no_target_city_offices_returns_nothing(mock_requests, make_employer):
    probe = {
        "total": 500,
        "facets": [
            {
                "facetParameter": "locations",
                "values": [{"id": "ny-id", "descriptor": "New York, HQ", "count": 500}],
            }
        ],
    }
    mock_requests.register(
        "POST", f"acme.wd5.myworkdayjobs.com{LIST_PATH}", _by_body(probe, probe)
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    assert list(fetch_postings(employer)) == []


def test_fetch_postings_detail_fetch_failure_falls_back_to_list_fields(
    mock_requests, make_employer
):
    page_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Delisted Role",
                "externalPath": "/job/London/Delisted-Role_R-002",
                "bulletFields": ["R-002"],
                "locationsText": "London, Luke Street (Eagle Lab)",
            }
        ],
    }
    mock_requests.register(
        "POST",
        f"acme.wd5.myworkdayjobs.com{LIST_PATH}",
        _by_body(_probe_with_locations_facet(), page_response),
    )
    mock_requests.get(
        "acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/London/Delisted-Role_R-002",
        status_code=404,
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    posting = postings[0]
    # detail fetch failed (delisted between list and detail) — falls
    # back to the list response's own fields rather than dropping it
    assert posting["title"] == "Delisted Role"
    assert posting["location_raw"] == "London, Luke Street (Eagle Lab)"
    assert posting["description_text"] is None


def test_fetch_postings_missing_config_yields_nothing(mock_requests, make_employer):
    employer = make_employer("workday", {"company": "acme"})  # missing wd_instance/site
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []


# T035 — regression fixtures for descriptor shapes that previously yielded
# no location IDs (confirmed via T037 live debug-pod investigation).


def _probe_space_separated_locations():
    """Citi-style: city+country with double-spaces, no comma delimiter."""
    return {
        "total": 2,
        "facets": [
            {
                "facetParameter": "locations",
                "values": [
                    {
                        "id": "london-space-id",
                        "descriptor": "London  United Kingdom",
                        "count": 1,
                    },
                    {
                        "id": "dublin-space-id",
                        "descriptor": "Dublin  Ireland",
                        "count": 1,
                    },
                    {"id": "ny-id", "descriptor": "New York  New York  United States", "count": 500},
                ],
            }
        ],
    }


def test_fetch_postings_space_separated_descriptor_matches_target_city(
    mock_requests, make_employer
):
    """T035a: descriptors like "London  United Kingdom" (Citi-style, no comma)
    must still resolve to a London location ID and drive a filtered fetch."""
    probe = _probe_space_separated_locations()
    page_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Analyst",
                "externalPath": "/job/London/Analyst_C-001",
                "bulletFields": ["C-001"],
                "locationsText": "London  United Kingdom",
            }
        ],
    }
    mock_requests.register(
        "POST", f"acme.wd5.myworkdayjobs.com{LIST_PATH}", _by_body(probe, page_response)
    )
    mock_requests.get(
        "acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/London/Analyst_C-001",
        status_code=404,
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    assert postings[0]["external_id"] == "C-001"


def test_fetch_postings_city_prefix_descriptor_matches_target_city(
    mock_requests, make_employer
):
    """T035b: descriptors like "Dublin Office - George's Quay House" (Fidelity-style,
    city is first whitespace token, no comma) must resolve to a Dublin location ID."""
    probe = {
        "total": 1,
        "facets": [
            {
                "facetParameter": "locations",
                "values": [
                    {
                        "id": "dublin-office-id",
                        "descriptor": "Dublin Office - George's Quay House",
                        "count": 1,
                    }
                ],
            }
        ],
    }
    page_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Fund Accountant",
                "externalPath": "/job/Dublin/Fund-Accountant_F-001",
                "bulletFields": ["F-001"],
                "locationsText": "Dublin Office",
            }
        ],
    }
    mock_requests.register(
        "POST", f"acme.wd5.myworkdayjobs.com{LIST_PATH}", _by_body(probe, page_response)
    )
    mock_requests.get(
        "acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/Dublin/Fund-Accountant_F-001",
        status_code=404,
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    assert postings[0]["external_id"] == "F-001"


def test_fetch_postings_alias_prefix_descriptor_matches_target_city(
    mock_requests, make_employer
):
    """T035c: descriptors like "Cannon Street Office" (Fidelity-style) must
    match via the "cannon street" -> "london" alias-prefix check."""
    probe = {
        "total": 1,
        "facets": [
            {
                "facetParameter": "locations",
                "values": [
                    {
                        "id": "cannon-street-id",
                        "descriptor": "Cannon Street Office",
                        "count": 1,
                    }
                ],
            }
        ],
    }
    page_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Investment Manager",
                "externalPath": "/job/London/Investment-Manager_F-002",
                "bulletFields": ["F-002"],
                "locationsText": "Cannon Street Office",
            }
        ],
    }
    mock_requests.register(
        "POST", f"acme.wd5.myworkdayjobs.com{LIST_PATH}", _by_body(probe, page_response)
    )
    mock_requests.get(
        "acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/London/Investment-Manager_F-002",
        status_code=404,
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    assert postings[0]["external_id"] == "F-002"


# T036 — genuinely-zero case: employer has offices but none in target cities.


def test_fetch_postings_no_comma_descriptors_none_in_target_city_returns_nothing(
    mock_requests, make_employer
):
    """T036: space-separated descriptors for non-target cities (e.g. NVIDIA-style
    "Belfast  United Kingdom", "Bristol  United Kingdom") must not falsely match."""
    probe = {
        "total": 300,
        "facets": [
            {
                "facetParameter": "locations",
                "values": [
                    {"id": "belfast-id", "descriptor": "Belfast  United Kingdom", "count": 100},
                    {"id": "bristol-id", "descriptor": "Bristol  United Kingdom", "count": 100},
                    {"id": "cambridge-id", "descriptor": "Cambridge  United Kingdom", "count": 100},
                ],
            }
        ],
    }
    mock_requests.register(
        "POST", f"acme.wd5.myworkdayjobs.com{LIST_PATH}", _by_body(probe, probe)
    )
    employer = make_employer(
        "workday", {"company": "acme", "wd_instance": "wd5", "site": "careers"}
    )

    assert list(fetch_postings(employer)) == []
