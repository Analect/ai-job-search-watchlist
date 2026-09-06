"""T028: fixture test for pipelines/adapters/eightfold.py, covering
both paths — the public jobs API (millennium-management-shaped) and
the sitemap+JSON-LD fallback (lam-research-shaped, PCSX disabled)."""

import pytest

from pipelines.adapters.eightfold import fetch_postings
from pipelines.common.http_retry import AntiBotBlockedError

CAREERS_HTML = """
<html><script>window._EF_GROUP_ID = "mlp.com";</script></html>
"""


def test_fetch_postings_via_public_api(mock_requests, make_employer):
    mock_requests.get("career.mlp.com/careers", text_data=CAREERS_HTML)
    mock_requests.get(
        "career.mlp.com/api/apply/v2/jobs/123",
        json_data={"job_description": "<p>Trade things.</p>"},
    )

    def jobs_responder(request):
        from tests.adapters.conftest import FakeResponse

        if "London" in request.url:
            return FakeResponse(
                200,
                json_data={
                    "positions": [
                        {
                            "id": 123,
                            "name": "Quant Researcher",
                            "canonicalPositionUrl": "https://career.mlp.com/jobs/123",
                            "locations": ["London"],
                            "department": "Research",
                            "work_location_option": "remote",
                            "t_create": 1735689600,
                        }
                    ],
                    "count": 1,
                },
            )
        return FakeResponse(200, json_data={"positions": [], "count": 0})

    mock_requests.register("GET", "career.mlp.com/api/apply/v2/jobs?", jobs_responder)
    employer = make_employer("eightfold", {"host": "career.mlp.com"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    posting = postings[0]
    assert posting["external_id"] == "123"
    assert posting["title"] == "Quant Researcher"
    assert posting["location_raw"] == "London"
    assert posting["department"] == "Research"
    assert posting["is_remote"] is True
    assert posting["posted_date"] == "2025-01-01"
    assert posting["description_text"] == "<p>Trade things.</p>"


SITEMAP_XML = """<?xml version="1.0"?>
<urlset>
<url><loc>https://lamresearch.eightfold.ai/careers/job/1001</loc></url>
</urlset>
"""

JOBPOSTING_PAGE = """
<html><script type="application/ld+json">
{"@type": "JobPosting", "title": "Process Engineer",
 "employmentType": "FULL_TIME", "datePosted": "2026-05-01",
 "description": "Build semiconductor equipment.",
 "jobLocation": {"address": {"addressLocality": "Fremont",
   "addressRegion": "CA", "addressCountry": {"name": "United States"}}}}
</script></html>
"""


def test_fetch_postings_falls_back_to_sitemap_when_pcsx_blocked(mock_requests, make_employer):
    mock_requests.get(
        "lamresearch.eightfold.ai/careers",
        text_data="<html>no group id here</html>",
    )
    mock_requests.get("lamresearch.eightfold.ai/careers/sitemap.xml", text_data=SITEMAP_XML)
    mock_requests.get(
        "lamresearch.eightfold.ai/careers/job/1001", text_data=JOBPOSTING_PAGE
    )
    employer = make_employer("eightfold", {"host": "lamresearch.eightfold.ai"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 1
    posting = postings[0]
    assert posting["external_id"] == "1001"
    assert posting["title"] == "Process Engineer"
    assert posting["location_city"] == "Fremont"
    assert posting["location_region"] == "CA"
    assert posting["location_country"] == "United States"
    assert posting["posted_date"] == "2026-05-01"
    assert posting["description_text"] == "Build semiconductor equipment."


def test_sitemap_fallback_propagates_anti_bot_block_instead_of_swallowing_it(
    mock_requests, make_employer
):
    # Regression test for the real bug found live: a 403 mid-sitemap-scan
    # must fail the whole employer loudly, not look like a normal
    # per-page skip.
    mock_requests.get(
        "lamresearch.eightfold.ai/careers", text_data="<html>no group id</html>"
    )
    mock_requests.get("lamresearch.eightfold.ai/careers/sitemap.xml", text_data=SITEMAP_XML)
    mock_requests.get("lamresearch.eightfold.ai/careers/job/1001", status_code=403)
    employer = make_employer("eightfold", {"host": "lamresearch.eightfold.ai"})

    with pytest.raises(AntiBotBlockedError):
        list(fetch_postings(employer))


def test_fetch_postings_no_host_yields_nothing(mock_requests, make_employer):
    employer = make_employer("eightfold", {})
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []
