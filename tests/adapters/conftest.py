"""Shared fixture-test infrastructure for the 8 ATS adapters
(ats-adapter.contract.md).

Mocks at `requests.Session.send` — the one layer every adapter's HTTP
call ultimately goes through, whether via `fetch_json_with_retry`
(`requests.request`), a raw `requests.get` (Eightfold's HTML/sitemap
fetches), or dlt's `RESTClient` (Workday's paginated list call, which
also uses a `requests.Session` internally). One mocking strategy works
for all 8 adapters rather than a different approach per HTTP client.
"""

import json as json_module

import pytest
import requests

from pipelines.common.types import Employer


class FakeResponse(requests.Response):
    def __init__(self, status_code, json_data=None, text_data=None, url=""):
        super().__init__()
        self.status_code = status_code
        self.url = url
        if text_data is not None:
            self._content = text_data.encode()
        elif json_data is not None:
            self._content = json_module.dumps(json_data).encode()
        else:
            self._content = b""


class MockRequests:
    """Registers (method, url_substring) -> FakeResponse (or a callable
    taking the PreparedRequest and returning one, for a URL needing a
    dynamic response). The longest matching url_substring wins, not
    registration order. Call `.get(...)`/`.post(...)` to register, or
    `.calls` to inspect what was actually requested."""

    def __init__(self):
        self._handlers: list[tuple[str, str, FakeResponse]] = []
        self.calls: list[tuple[str, str]] = []

    def register(self, method: str, url_substring: str, response: FakeResponse):
        self._handlers.append((method.upper(), url_substring, response))

    def get(self, url_substring: str, status_code: int = 200, **kwargs):
        self.register(
            "GET", url_substring, FakeResponse(status_code, url=url_substring, **kwargs)
        )

    def post(self, url_substring: str, status_code: int = 200, **kwargs):
        self.register(
            "POST", url_substring, FakeResponse(status_code, url=url_substring, **kwargs)
        )

    def __call__(self, request, **kwargs):
        # Note: setting a plain callable instance as `requests.Session.send`
        # does NOT bind `self` to the session the way a real method would
        # (only functions/descriptors do that) — `session.send(prep, ...)`
        # calls this with `prep` as `request`, not with the session first.
        self.calls.append((request.method, request.url))
        # Longest-substring-first, not registration order — otherwise a
        # shorter pattern registered earlier (e.g. ".../careers") can
        # accidentally swallow a more specific one (".../careers/sitemap.xml").
        matches = [
            (method, url_substring, response)
            for method, url_substring, response in self._handlers
            if request.method.upper() == method and url_substring in request.url
        ]
        if matches:
            _, _, response = max(matches, key=lambda h: len(h[1]))
            return response(request) if callable(response) else response
        raise AssertionError(f"unmocked request: {request.method} {request.url}")


@pytest.fixture
def mock_requests(monkeypatch):
    mock = MockRequests()
    monkeypatch.setattr(requests.Session, "send", mock)
    return mock


@pytest.fixture
def make_employer():
    def _make(ats_type: str, ats_config: dict, slug: str = "test-employer") -> Employer:
        return Employer(
            id="11111111-1111-1111-1111-111111111111",
            slug=slug,
            name="Test Employer",
            ats_type=ats_type,
            ats_config=ats_config,
        )

    return _make
