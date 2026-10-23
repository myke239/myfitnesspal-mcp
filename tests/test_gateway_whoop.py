import httpx
import pytest
from starlette.testclient import TestClient

from myfitnesspal_mcp.gateway import create_gateway

ORIGIN = "https://shared.example.com"


def test_whoop_proxy_routes_metadata_and_tokens_without_garmin_collision(tmp_path):
    requests = []

    def backend(request):
        requests.append(request)
        return httpx.Response(
            401, stream=httpx.ByteStream(b"Own resource token required")
        )

    app, _ = create_gateway(
        ORIGIN,
        directory=tmp_path,
        transport=httpx.MockTransport(backend),
        whoop_port=8789,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        for path in (
            "/mcp/whoop/",
            "/mcp/whoop/register",
            "/mcp/whoop/token",
            "/.well-known/oauth-authorization-server/mcp/whoop",
            "/.well-known/oauth-protected-resource/mcp/whoop/",
        ):
            response = client.post(
                path,
                headers={
                    "Authorization": "Bearer whoop-test",
                    "x-forwarded-host": "evil.example",
                },
                content=b"bounded-request",
            )
            assert response.status_code == 401
            assert requests[-1].url.port == 8789
            assert requests[-1].url.path == path
            assert requests[-1].headers["host"] == "shared.example.com"
            assert requests[-1].headers["authorization"] == "Bearer whoop-test"
            assert "x-forwarded-host" not in requests[-1].headers
        assert client.get("/mcp/whoop").status_code == 401
        assert requests[-1].url.path == "/mcp/whoop/"
        assert client.get("/mcp/garmin-connect").status_code == 401
        assert requests[-1].url.port == 8787
        assert requests[-1].url.path == "/mcp/garmin-connect/"
        assert client.get("/mcp/myfitnesspal").status_code == 401
        assert requests[-1].url.port == 8787  # MFP handled internally, not forwarded.
        assert client.post("/mcp/whoop/token", content=b"x" * 16385).status_code == 413
        assert client.get("/mcp/whoop/health?ticket=synthetic").status_code == 401
        assert requests[-1].url.query == b"ticket=synthetic"


@pytest.mark.parametrize("port", [80, 65536, 8787, 8788])
def test_whoop_port_must_be_separate(port):
    with pytest.raises(ValueError):
        create_gateway(ORIGIN, whoop_port=port)
