"""T030: fixture test for pipelines/adapters/oracle_hcm.py, modeled on
a recorded shape of the recruitingCEJobRequisitions REST API."""

from pipelines.adapters.oracle_hcm import fetch_postings


def _list_response(total, items):
    return {"items": [{"TotalJobsCount": total, "requisitionList": items}]}


def test_fetch_postings_filters_by_location_before_detail_fetch(mock_requests, make_employer):
    items = [
        {
            "Id": 1001,
            "Title": "London Analyst",
            "PrimaryLocation": "London, England, United Kingdom",
            "JobSchedule": "Full-time",
            "PostedDate": "2026-08-01",
            "workLocation": [
                {"TownOrCity": "London", "Region2": "England", "Country": "United Kingdom"}
            ],
        },
        {
            "Id": 1002,
            "Title": "New York Analyst",
            "PrimaryLocation": "New York, NY, United States",
            "JobSchedule": "Full-time",
            "PostedDate": "2026-08-01",
        },
    ]
    mock_requests.get(
        "jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        json_data=_list_response(2, items),
    )
    mock_requests.get(
        "recruitingCEJobRequisitionDetails",
        json_data={"items": [{"ExternalDescriptionStr": "<p>Analyze markets.</p>"}]},
    )
    employer = make_employer("oracle_hcm", {"host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"})

    postings = list(fetch_postings(employer))

    # only the London posting matches TARGET_CITIES — the detail fetch
    # (and its API cost) is skipped entirely for New York
    assert len(postings) == 1
    posting = postings[0]
    assert posting["external_id"] == "1001"
    assert posting["title"] == "London Analyst"
    assert posting["location_city"] == "London"
    assert posting["location_region"] == "England"
    assert posting["location_country"] == "United Kingdom"
    assert posting["posted_date"] == "2026-08-01"
    assert posting["description_text"] == "<p>Analyze markets.</p>"
    detail_calls = [c for c in mock_requests.calls if "Details" in c[1]]
    assert len(detail_calls) == 1


def test_fetch_postings_paginates_via_manual_offset(mock_requests, make_employer):
    # Exact literal URLs (not loose fragments) — page 2's URL is page 1's
    # URL plus a ",offset=200" suffix, so it's both a superstring (safe
    # against the "longest substring wins" matcher) and the real shape
    # Oracle's compound `finder=...,offset=N` pagination actually uses.
    page_1_url = (
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.workLocation"
        "&finder=findReqs;siteNumber=CX_1001,limit=200,sortBy=POSTING_DATES_DESC"
    )
    page_2_url = page_1_url + ",offset=200"

    page_1_items = [
        {
            "Id": i,
            "Title": f"London Role {i}",
            "PrimaryLocation": "London, England, United Kingdom",
        }
        for i in range(1, 201)  # Id=0 is falsy — the adapter's own `if not req_id` skips it
    ]
    page_2_items = [
        {
            "Id": 201,
            "Title": "London Role 201",
            "PrimaryLocation": "London, England, United Kingdom",
        }
    ]
    mock_requests.get(page_1_url, json_data=_list_response(201, page_1_items))
    mock_requests.get(page_2_url, json_data=_list_response(201, page_2_items))
    mock_requests.get("recruitingCEJobRequisitionDetails", json_data={"items": [{}]})
    employer = make_employer("oracle_hcm", {"host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"})

    postings = list(fetch_postings(employer))

    assert len(postings) == 201


def test_fetch_postings_zero_total_returns_nothing(mock_requests, make_employer):
    mock_requests.get(
        "recruitingCEJobRequisitions?onlyData=true", json_data=_list_response(0, [])
    )
    employer = make_employer("oracle_hcm", {"host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"})

    assert list(fetch_postings(employer)) == []


def test_fetch_postings_missing_config_yields_nothing(mock_requests, make_employer):
    employer = make_employer("oracle_hcm", {"host": "jpmc.fa.oraclecloud.com"})  # no site
    assert list(fetch_postings(employer)) == []
    assert mock_requests.calls == []
