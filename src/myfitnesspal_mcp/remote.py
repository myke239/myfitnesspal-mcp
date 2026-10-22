"""Single-owner OAuth server. Consent is granted only by the local terminal."""

import argparse
import hashlib
import html
import json
import os
import secrets
import shlex
import sys
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from .server import create_server
from .storage import TokenStore, data_directory, session_lock

READ_SCOPE = "myfitnesspal:read"
WRITE_SCOPE = "myfitnesspal:write"
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 86400
CALLBACK_HOSTS = {"chatgpt.com", "chat.openai.com"}


def public_origin(value):
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Provide a public HTTPS origin without a path, query or credentials"
        )
    return "https://" + parts.hostname.lower()


def valid_callback(value):
    parts = urlsplit(str(value))
    return (
        parts.scheme == "https"
        and parts.hostname in CALLBACK_HOSTS
        and parts.port in (None, 443)
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and (
            parts.path == "/connector_platform_oauth_redirect"
            or (
                parts.path.startswith("/connector/oauth/")
                and len(parts.path.removeprefix("/connector/oauth/")) > 0
                and "/" not in parts.path.removeprefix("/connector/oauth/")
            )
            or parts.path.startswith("/oauth/callback/")
            or parts.path == "/oauth/callback"
            or (
                parts.path.startswith("/aip/")
                and parts.path.endswith("/oauth/callback")
            )
        )
    )


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def approval_command(ticket):
    args = [sys.executable, "-m", "myfitnesspal_mcp.remote", "approve", ticket]
    if os.name == "nt":
        return "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
    return shlex.join(args)


class OwnerRefresh(RefreshToken):
    family: str


class OwnerProvider:
    def __init__(self, origin, directory=None, prefix="", resource_path=None):
        self.origin = public_origin(origin)
        if prefix not in ("", "/myfitnesspal"):
            raise ValueError("Unsupported connector prefix")
        self.prefix = prefix
        self.base_url = self.origin + prefix
        self.resource_path = resource_path or prefix + "/mcp"
        if not self.resource_path.startswith("/") or self.resource_path.endswith("/"):
            raise ValueError("Invalid MCP resource path")
        self.resource = self.origin + self.resource_path
        self.store = TokenStore(directory or data_directory() / "remote-oauth")

    @contextmanager
    def state(self):
        with session_lock(self.store):
            state = (
                json.loads(self.store.load())
                if self.store.exists()
                else {
                    "origin": self.origin,
                    "prefix": self.prefix,
                    "resource_path": self.resource_path,
                    "clients": {},
                    "pending": {},
                    "codes": {},
                    "access": {},
                    "refresh": {},
                }
            )
            if (
                state["origin"] != self.origin
                or state.get("prefix", "") != self.prefix
                or state.get("resource_path", state.get("prefix", "") + "/mcp")
                != self.resource_path
            ):
                raise ValueError(
                    "Public origin or MCP resource changed. Revoke/reset remote connections first."
                )
            now = time.time()
            for collection in ("pending", "codes", "access", "refresh"):
                state[collection] = {
                    k: v for k, v in state[collection].items() if v["expires_at"] > now
                }
            yield state
            self.store.save(json.dumps(state))

    async def get_client(self, client_id):
        with self.state() as state:
            value = state["clients"].get(client_id)
            return OAuthClientInformationFull.model_validate(value) if value else None

    async def register_client(self, client_info):
        if (
            not client_info.redirect_uris
            or len(client_info.redirect_uris) > 4
            or not all(valid_callback(uri) for uri in client_info.redirect_uris)
            or client_info.token_endpoint_auth_method
            not in ("none", "client_secret_post", "client_secret_basic")
        ):
            raise RegistrationError(
                "invalid_redirect_uri", "Only ChatGPT HTTPS callbacks are allowed"
            )
        with self.state() as state:
            if len(state["clients"]) >= 128:
                raise RegistrationError(
                    "invalid_client_metadata", "Registration capacity reached"
                )
            state["clients"][client_info.client_id] = client_info.model_dump(
                mode="json"
            )

    async def authorize(self, client, params):
        if (
            params.resource != self.resource
            or READ_SCOPE not in params.scopes
            or not set(params.scopes) <= {READ_SCOPE, WRITE_SCOPE}
            or not params.state
            or len(params.state) > 2048
            or not valid_callback(params.redirect_uri)
        ):
            raise AuthorizeError(
                "invalid_request", "Invalid resource, scope, state or callback"
            )
        ticket = secrets.token_urlsafe(32)
        with self.state() as state:
            if len(state["pending"]) >= 32:
                raise AuthorizeError(
                    "temporarily_unavailable", "Consent capacity reached"
                )
            state["pending"][ticket] = {
                "client_id": client.client_id,
                "params": params.model_dump(mode="json"),
                "approved": False,
                "expires_at": time.time() + 300,
            }
        return self.base_url + "/consent?ticket=" + ticket

    def consent(self, ticket):
        with self.state() as state:
            pending = state["pending"].get(ticket)
            if not pending:
                return HTMLResponse(
                    "Connection request expired. Start again in ChatGPT.",
                    status_code=400,
                )
            if not pending["approved"]:
                # No login cookie, secret, password or browser approval can grant access.
                return HTMLResponse(
                    "<h1>Approve your MyFitnessPal connection on your PC</h1>"
                    "<p>This gives ChatGPT access to your MyFitnessPal account with scopes: "
                    + html.escape(" ".join(pending["params"]["scopes"]))
                    + ". "
                    "Only approve a connection you just started.</p>"
                    "<p>On the PC running this server, open "
                    + ("PowerShell" if os.name == "nt" else "a terminal")
                    + " and paste this entire command. You can run it from any folder; "
                    "no Python environment activation is needed.</p><pre>"
                    + html.escape(approval_command(ticket))
                    + "</pre><p>Review the connection and type APPROVE when prompted. "
                    "Then return here and select Continue. The request expires after five minutes.</p>"
                    '<form method="get" action="'
                    + self.prefix
                    + '/consent"><input type="hidden" name="ticket" value="'
                    + html.escape(ticket, quote=True)
                    + '"><button>Continue</button></form>'
                )
            params = AuthorizationParams.model_validate(pending["params"])
            code = secrets.token_urlsafe(32)
            state["codes"][key(code)] = AuthorizationCode(
                code=code,
                client_id=pending["client_id"],
                scopes=params.scopes,
                expires_at=time.time() + 60,
                code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=self.resource,
                subject="local-owner",
            ).model_dump(mode="json")
            del state["pending"][ticket]
            return RedirectResponse(
                construct_redirect_uri(
                    str(params.redirect_uri), code=code, state=params.state
                ),
                status_code=302,
            )

    def approve(self, ticket):
        with self.state() as state:
            pending = state["pending"].get(ticket)
            if not pending:
                raise ValueError("Connection request expired or not found")
            print("Callback:", pending["params"]["redirect_uri"])
            print("Client ID:", pending["client_id"])
            scopes = pending["params"]["scopes"]
            print("Requested scopes:", " ".join(scopes))
            reviewed = json.dumps(
                [pending["client_id"], pending["params"]], sort_keys=True
            )
        # Do not hold the session lock while the owner reviews the request.
        if not sys.stdin.isatty():
            raise ValueError("Approval requires your interactive local terminal")
        action = (
            "read and modify your MyFitnessPal account"
            if WRITE_SCOPE in scopes
            else "read your MyFitnessPal diary, nutrition and measurements"
        )
        if (
            input("Allow this connection to " + action + "? Type APPROVE: ")
            != "APPROVE"
        ):
            raise ValueError("Not approved")
        with self.state() as state:
            pending = state["pending"].get(ticket)
            if not pending:
                raise ValueError("Connection request expired or not found")
            if (
                json.dumps([pending["client_id"], pending["params"]], sort_keys=True)
                != reviewed
            ):
                raise ValueError(
                    "Connection changed during review. Restart authorization."
                )
            pending["approved"] = True

    async def load_authorization_code(self, client, authorization_code):
        with self.state() as state:
            value = state["codes"].get(key(authorization_code))
            return (
                AuthorizationCode.model_validate(value)
                if value and value["client_id"] == client.client_id
                else None
            )

    def issue(self, state, client_id, family, scopes):
        if len(state["access"]) >= 256 or len(state["refresh"]) >= 128:
            raise TokenError(
                "invalid_grant", "Token capacity reached; reset remote connections"
            )
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        state["access"][key(access)] = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + ACCESS_SECONDS,
            resource=self.resource,
            subject="local-owner",
            claims={"family": family},
        ).model_dump(mode="json")
        state["refresh"][key(refresh)] = OwnerRefresh(
            token=refresh,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + REFRESH_SECONDS,
            resource=self.resource,
            subject="local-owner",
            family=family,
        ).model_dump(mode="json")
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            token_type="Bearer",
            expires_in=ACCESS_SECONDS,
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        with self.state() as state:
            value = state["codes"].pop(key(authorization_code.code), None)
            if (
                not value
                or value["client_id"] != client.client_id
                or value["resource"] != self.resource
            ):
                raise TokenError(
                    "invalid_grant", "Code expired, invalid or already consumed"
                )
            return self.issue(
                state, client.client_id, secrets.token_urlsafe(24), value["scopes"]
            )

    async def load_refresh_token(self, client, refresh_token):
        with self.state() as state:
            value = state["refresh"].get(key(refresh_token))
            return (
                OwnerRefresh.model_validate(value)
                if value and value["client_id"] == client.client_id
                else None
            )

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        if (
            READ_SCOPE not in scopes
            or not set(scopes) <= set(refresh_token.scopes)
            or refresh_token.resource != self.resource
        ):
            raise TokenError(
                "invalid_scope", "Refresh cannot escalate account permissions"
            )
        with self.state() as state:
            value = state["refresh"].pop(key(refresh_token.token), None)
            if not value or value["client_id"] != client.client_id:
                raise TokenError("invalid_grant", "Invalid refresh token")
            # Replace the family's previous access token, bounding storage during rotation.
            state["access"] = {
                k: v
                for k, v in state["access"].items()
                if v["claims"]["family"] != refresh_token.family
            }
            return self.issue(state, client.client_id, refresh_token.family, scopes)

    async def load_access_token(self, token):
        with self.state() as state:
            value = state["access"].get(key(token))
            return AccessToken.model_validate(value) if value else None

    async def revoke_token(self, token):
        family = (
            token.family
            if isinstance(token, OwnerRefresh)
            else (token.claims or {}).get("family")
        )
        with self.state() as state:
            state["access"] = {
                k: v
                for k, v in state["access"].items()
                if v["claims"]["family"] != family
            }
            state["refresh"] = {
                k: v for k, v in state["refresh"].items() if v["family"] != family
            }


class Boundary:
    """Apply host/origin checks, bounded bodies and a process-wide request rate cap."""

    def __init__(self, app, origin, port, prefix="", mcp_paths=None, resource=None):
        self.prefix = prefix
        self.mcp_paths = mcp_paths or {prefix + "/mcp"}
        self.app, self.origin = app, origin
        self.resource = resource or origin + prefix + "/mcp"
        self.hosts = {urlsplit(origin).netloc, f"127.0.0.1:{port}", f"localhost:{port}"}
        self.window, self.count = time.monotonic(), 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        if (
            headers.get("host") not in self.hosts
            or headers.get("origin", self.origin) != self.origin
        ):
            return await JSONResponse(
                {"error": "Invalid host or origin"}, status_code=403
            )(scope, receive, send)
        if time.monotonic() - self.window >= 60:
            self.window, self.count = time.monotonic(), 0
        self.count += 1
        if self.count > 120:
            return await JSONResponse(
                {"error": "Rate limit exceeded"}, status_code=429
            )(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > (
                3 * 1024 * 1024 if scope["path"] in self.mcp_paths else 16384
            ):
                return await JSONResponse(
                    {"error": "Request too large"}, status_code=413
                )(scope, receive, send)
            if not message.get("more_body", False):
                break
        if scope["path"] in (self.prefix + "/token", self.prefix + "/revoke"):
            form = parse_qs(
                bytes(body).decode("utf-8", errors="replace"), keep_blank_values=True
            )
            # SDK 1.30 does not pass the requested token resource to the provider.
            # Refuse resource overrides; issued tokens stay bound to this connector.
            if "resource" in form and form["resource"] != [
                self.resource
            ]:
                return await JSONResponse({"error": "invalid_target"}, status_code=400)(
                    scope, receive, send
                )
            # SDK revocation schema requires the optional client_secret field.
            # An empty field enables standard public-client revocation; the SDK
            # still validates registered client authentication independently.
            if scope["path"] == self.prefix + "/revoke" and "client_secret" not in form:
                body.extend(b"&client_secret=")
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        response_start = None
        response_body = bytearray()

        async def secure_send(message):
            nonlocal response_start
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                    (
                        b"content-security-policy",
                        b"default-src 'none'; form-action 'self'; frame-ancestors 'none'",
                    ),
                ]
                headers = dict(message["headers"])
                # Finite JSON/HTML responses use explicit lengths. Some Windows
                # traffic filters strip chunk framing while retaining its header.
                if not headers.get(b"content-type", b"").startswith(
                    b"text/event-stream"
                ):
                    response_start = message
                    return
            if message["type"] == "http.response.body" and response_start is not None:
                response_body.extend(message.get("body", b""))
                if message.get("more_body", False):
                    return
                response_start["headers"] = [
                    (name, value)
                    for name, value in response_start["headers"]
                    if name.lower() not in (b"content-length", b"transfer-encoding")
                ]
                response_start["headers"].append(
                    (b"content-length", str(len(response_body)).encode())
                )
                await send(response_start)
                response_start = None
                message = {
                    "type": "http.response.body",
                    "body": bytes(response_body),
                    "more_body": False,
                }
            await send(message)

        await self.app(scope, replay, secure_send)


def create_http_app(
    origin, port=8788, directory=None, service=None, prefix="", resource_path=None
):
    provider = OwnerProvider(origin, directory, prefix, resource_path)
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(provider.base_url),
        resource_server_url=AnyHttpUrl(provider.resource),
        validate_token_resource=True,
        required_scopes=[READ_SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[READ_SCOPE, WRITE_SCOPE],
            default_scopes=[READ_SCOPE, WRITE_SCOPE],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    security = TransportSecuritySettings(
        allowed_hosts=[
            urlsplit(provider.origin).netloc,
            f"127.0.0.1:{port}",
            f"localhost:{port}",
        ],
        allowed_origins=[provider.origin],
    )
    server = create_server(
        service,
        remote_access=True,
        write_directory=provider.store.directory / "writes"
        if directory is not None
        else None,
        streamable_http_path=provider.resource_path,
        host="127.0.0.1",
        port=port,
        auth=auth,
        auth_server_provider=provider,
        transport_security=security,
        json_response=True,
        stateless_http=True,
        max_request_body_size=3 * 1024 * 1024,
    )

    @server.custom_route(prefix + "/consent", methods=["GET"])
    async def consent(request):
        return provider.consent(request.query_params.get("ticket", ""))

    @server.custom_route(prefix + "/health", methods=["GET"])
    async def health(request):
        from . import __version__

        return JSONResponse(
            {
                "status": "ready",
                "authentication": "oauth",
                "read_only": False,
                "server_version": __version__,
                "sdk_version": "2.1.2",
            }
        )

    app = server.streamable_http_app()
    if prefix:
        for route in app.routes:
            path = getattr(route, "path", "")
            if path in ("/authorize", "/token", "/register", "/revoke"):
                route.path = prefix + path
                from starlette.routing import compile_path

                route.path_regex, route.path_format, route.param_convertors = (
                    compile_path(route.path)
                )
            elif path == "/.well-known/oauth-authorization-server":
                route.path = path + prefix
                from starlette.routing import compile_path

                route.path_regex, route.path_format, route.param_convertors = (
                    compile_path(route.path)
                )

    # Publish both scopes, while retaining read-only grants for existing clients.
    from mcp.server.auth.routes import create_protected_resource_routes

    metadata_routes = create_protected_resource_routes(
        resource_url=AnyHttpUrl(provider.resource),
        authorization_servers=[AnyHttpUrl(provider.base_url)],
        scopes_supported=[READ_SCOPE, WRITE_SCOPE],
    )
    for replacement in metadata_routes:
        for index, route in enumerate(app.routes):
            if getattr(route, "path", None) == replacement.path:
                app.routes[index] = replacement
                break
        else:
            raise RuntimeError("Expected protected-resource metadata route missing")
    return Boundary(
        app,
        provider.origin,
        port,
        prefix,
        mcp_paths={provider.resource_path},
        resource=provider.resource,
    ), provider


def main():
    parser = argparse.ArgumentParser(
        description="Personal HTTP MyFitnessPal MCP with local-owner OAuth approval"
    )
    parser.add_argument("command", choices=["serve", "approve", "reset"])
    parser.add_argument("ticket", nargs="?")
    parser.add_argument("--public-url")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    store = TokenStore(data_directory() / "remote-oauth")
    if args.command == "reset":
        if (
            not sys.stdin.isatty()
            or input("Revoke all remote connections? Type RESET: ") != "RESET"
        ):
            raise SystemExit("Not reset")
        with session_lock(store):
            store.clear()
        print("All remote connections revoked. Reconnect in ChatGPT.")
        return
    origin = args.public_url
    if not origin and store.exists():
        origin = json.loads(store.load())["origin"]
    if not origin:
        raise SystemExit("Provide --public-url https://your-tunnel-host")
    saved = json.loads(store.load()) if store.exists() else {}
    prefix = saved.get("prefix", "")
    resource_path = saved.get("resource_path")
    if args.command == "approve":
        OwnerProvider(origin, prefix=prefix, resource_path=resource_path).approve(
            args.ticket
        )
        print("Approved. Return to the browser and select Continue.")
    else:
        if not 1024 <= args.port <= 65535:
            raise SystemExit("Use an unprivileged local port")
        import uvicorn

        app, _ = create_http_app(
            origin, args.port, prefix=prefix, resource_path=resource_path
        )
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
            access_log=False,
            proxy_headers=False,
            timeout_keep_alive=5,
            limit_concurrency=16,
        )


if __name__ == "__main__":
    main()
