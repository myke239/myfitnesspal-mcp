import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from myfitnesspal_mcp.remote import create_http_app
from myfitnesspal_mcp.windows_setup import (
    PAGES,
    approve_connection,
    review_connection,
    verification_failure,
)


def test_verification_failure_preserves_safe_diagnostic():
    message = verification_failure("Firefox", "Could not access MyFitnessPal.")
    assert "Could not access MyFitnessPal." in message
    assert "Firefox profile" in message


def test_chromium_verification_failure_suggests_firefox():
    message = verification_failure("Chrome", "Cannot read chrome cookies.")
    assert "Cannot read chrome cookies." in message
    assert "try Firefox" in message


def test_verification_failure_has_fallback_without_diagnostic():
    message = verification_failure("Edge", "")
    assert "Could not verify your sign-in in Edge." in message
    assert "choose Firefox" in message
ORIGIN = "https://shared.example.com"
RESOURCE = ORIGIN + "/mcp/myfitnesspal"
CALLBACK = "https://chatgpt.com/connector/oauth/test"



def _pending_request(directory):
    application, _provider = create_http_app(
        ORIGIN,
        directory=directory,
        prefix="/myfitnesspal",
        resource_path="/mcp/myfitnesspal",
    )
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    with TestClient(application, base_url=ORIGIN, follow_redirects=False) as client:
        registered = client.post(
            "/myfitnesspal/register",
            json={
                "redirect_uris": [CALLBACK],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "myfitnesspal:read myfitnesspal:write",
            },
        )
        identity = registered.json()["client_id"]
        response = client.get(
            "/myfitnesspal/authorize",
            params={
                "client_id": identity,
                "response_type": "code",
                "redirect_uri": CALLBACK,
                "scope": "myfitnesspal:read myfitnesspal:write",
                "state": "browser-state",
                "resource": RESOURCE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        ticket = parse_qs(urlsplit(response.headers["location"]).query)["ticket"][0]
    return ticket


def test_connection_request_requires_local_review_and_approval(tmp_path):
    started = time.time()
    ticket = _pending_request(tmp_path / "oauth")
    review = review_connection(ORIGIN, ticket, started, tmp_path / "oauth")
    assert review["resource"] == RESOURCE
    assert review["scopes"] == ["myfitnesspal:read", "myfitnesspal:write"]

    approve_connection(ORIGIN, review, tmp_path / "oauth")
    with pytest.raises(RuntimeError, match="changed or expired"):
        approve_connection(ORIGIN, review, tmp_path / "oauth")


def test_connection_request_rejects_changed_request(tmp_path):
    started = time.time()
    ticket = _pending_request(tmp_path / "oauth")
    review = review_connection(ORIGIN, ticket, started, tmp_path / "oauth")
    _application, provider = create_http_app(
        ORIGIN,
        directory=tmp_path / "oauth",
        prefix="/myfitnesspal",
        resource_path="/mcp/myfitnesspal",
    )
    with provider.state() as state:
        state["pending"][ticket]["params"]["state"] = "changed"
    with pytest.raises(RuntimeError, match="changed or expired"):
        approve_connection(ORIGIN, review, tmp_path / "oauth")


def test_wizard_includes_chatgpt_and_shared_server_steps():
    assert PAGES["client"][0] == "Where will you use MyFitnessPal?"
    assert PAGES["hosting"][0] == "Set up your ChatGPT connection"
    assert PAGES["chatgpt"][0] == "Add MyFitnessPal in ChatGPT"
