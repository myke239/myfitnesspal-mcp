import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
from starlette.testclient import TestClient

from myfitnesspal_mcp.gateway import create_gateway
from myfitnesspal_mcp.service import Service

ORIGIN = "https://shared.example.com"
PREFIX = "/myfitnesspal"
MFP_PATH = "/mcp/myfitnesspal"
RESOURCE = ORIGIN + MFP_PATH
CALLBACK = "https://chatgpt.com/connector/oauth/test"


def test_shared_gateway_oauth_and_routing(tmp_path, monkeypatch):
    requests = []

    def garmin(request):
        requests.append(request)
        if request.url.path in {
            "/mcp",
            "/mcp/garmin-connect",
            "/mcp/garmin-connect/",
        }:
            return httpx.Response(
                401, stream=httpx.ByteStream(b"Garmin requires its own token")
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(b'{"issuer":"https://shared.example.com"}'),
        )

    monkeypatch.setattr(
        Service,
        "diary",
        lambda self, calendar_date: {"date": calendar_date, "food": "Oatmeal"},
    )
    app, provider = create_gateway(
        ORIGIN, directory=tmp_path / "oauth", transport=httpx.MockTransport(garmin)
    )
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        assert (
            client.get("/.well-known/oauth-authorization-server").json()["issuer"]
            == ORIGIN
        )
        assert requests[-1].headers["host"] == "shared.example.com"
        response = client.get(MFP_PATH)
        assert response.status_code == 401
        assert (
            "/.well-known/oauth-protected-resource/mcp/myfitnesspal"
            in response.headers["www-authenticate"]
        )
        metadata = client.get(
            "/.well-known/oauth-protected-resource/mcp/myfitnesspal"
        ).json()
        assert metadata["resource"] == RESOURCE
        assert client.get(PREFIX + "/mcp").status_code == 404
        assert metadata["authorization_servers"] == [ORIGIN + PREFIX]
        auth = client.get("/.well-known/oauth-authorization-server/myfitnesspal").json()
        assert auth["issuer"] == ORIGIN + PREFIX
        for name, suffix in (
            ("authorization_endpoint", "/authorize"),
            ("token_endpoint", "/token"),
            ("registration_endpoint", "/register"),
        ):
            assert auth[name] == ORIGIN + PREFIX + suffix
        identity = client.post(
            PREFIX + "/register",
            json={
                "redirect_uris": [CALLBACK],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "myfitnesspal:read",
            },
        ).json()["client_id"]
        verifier = "a" * 64
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        redirect = client.get(
            PREFIX + "/authorize",
            params={
                "client_id": identity,
                "response_type": "code",
                "redirect_uri": CALLBACK,
                "scope": "myfitnesspal:read",
                "state": "test-state",
                "resource": RESOURCE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert redirect.status_code == 302, redirect.text
        assert redirect.headers["location"].startswith(ORIGIN + PREFIX + "/consent?")
        ticket = parse_qs(urlsplit(redirect.headers["location"]).query)["ticket"][0]
        assert (
            'action="/myfitnesspal/consent"'
            in client.get(redirect.headers["location"]).text
        )
        with provider.state() as state:
            state["pending"][ticket]["approved"] = True
        redirect = client.get(PREFIX + "/consent", params={"ticket": ticket})
        code = parse_qs(urlsplit(redirect.headers["location"]).query)["code"][0]
        data = {
            "grant_type": "authorization_code",
            "client_id": identity,
            "code": code,
            "redirect_uri": CALLBACK,
            "code_verifier": verifier,
            "resource": ORIGIN + "/mcp",
        }
        assert client.post(PREFIX + "/token", data=data).status_code == 400
        data["resource"] = RESOURCE
        response = client.post(PREFIX + "/token", data=data)
        assert response.status_code == 200, response.text
        headers = {
            "Authorization": "Bearer " + response.json()["access_token"],
            "Accept": "application/json, text/event-stream",
        }
        result = client.post(
            MFP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_food_diary",
                    "arguments": {"calendar_date": "2026-10-15"},
                },
            },
        )
        assert result.status_code == 200 and "Oatmeal" in result.text
        assert client.get("/mcp", headers=headers).status_code == 401
        assert (
            client.get(
                MFP_PATH, headers={"Authorization": "Bearer garmin-token"}
            ).status_code
            == 401
        )
        assert (
            client.get(PREFIX + "/health", headers={"Host": "evil.example"}).status_code
            == 403
        )
        assert client.post("/token", content=b"x" * 16385).status_code == 413
        assert client.post("/mcp", content=b"x" * 20000).status_code == 401
        assert client.post(MFP_PATH, content=b"x" * 20000).status_code == 401
        assert (
            client.post("/mcp/garmin-connect", content=b"x" * 20000).status_code
            == 401
        )
        assert requests[-1].url.path == "/mcp/garmin-connect/"
        assert (
            client.post(
                "/mcp/garmin-connect", content=b"x" * (3 * 1024 * 1024 + 1)
            ).status_code
            == 413
        )
        assert (
            client.get(
                "/health", headers={"x-forwarded-host": "evil.example"}
            ).status_code
            == 200
        )
        assert "x-forwarded-host" not in requests[-1].headers
