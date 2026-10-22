"""One ngrok endpoint, independent Garmin and MyFitnessPal OAuth resources."""

import argparse
import json
import logging
import os
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .remote import Boundary, create_http_app, public_origin
from .storage import TokenStore, data_directory

PREFIX = "/myfitnesspal"
MFP_METADATA = {
    "/.well-known/oauth-protected-resource/myfitnesspal/mcp",
    "/.well-known/oauth-authorization-server/myfitnesspal",
}
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def create_gateway(
    origin, garmin_port=8787, port=8788, directory=None, service=None, transport=None
):
    origin = public_origin(origin)
    mfp, provider = create_http_app(origin, port, directory, service, prefix=PREFIX)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(130, connect=5),
        ) as client:
            app.state.backend = client
            async with mfp.app.router.lifespan_context(mfp.app):
                yield

    async def proxy(request):
        # The backend target is fixed; caller URLs and forwarding headers cannot select it.
        content = await request.body()
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_HEADERS
            and not k.lower().startswith("x-forwarded-")
            and k.lower() != "forwarded"
        }
        headers["host"] = urlsplit(origin).netloc
        path = request.url.path
        url = f"http://127.0.0.1:{garmin_port}{path}"
        if request.url.query:
            url += "?" + request.url.query
        outgoing = request.app.state.backend.build_request(
            request.method, url, headers=headers, content=content
        )
        try:
            response = await request.app.state.backend.send(outgoing, stream=True)
        except httpx.RequestError:
            return JSONResponse(
                {"error": "Garmin backend unavailable"}, status_code=503
            )

        async def stream():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            stream(),
            status_code=response.status_code,
            headers={
                k: v
                for k, v in response.headers.items()
                if k.lower() not in HOP_HEADERS
            },
        )

    backend = Starlette(
        routes=[
            Route(
                "/{path:path}",
                proxy,
                methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"],
            )
        ],
        lifespan=lifespan,
    )

    async def dispatch(scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (
            path == PREFIX or path.startswith(PREFIX + "/") or path in MFP_METADATA
        ):
            return await mfp(scope, receive, send)
        return await backend(scope, receive, send)

    # Both connectors retain their own inner boundary; cap requests before proxy buffering.
    return Boundary(
        dispatch, origin, port, PREFIX, mcp_paths={"/mcp", "/mcp/garmin-connect/", PREFIX + "/mcp"}
    ), provider


def read_garmin_state(directory, name):
    """Read existing Windows-encrypted state without changing Garmin's ACLs."""
    import win32crypt

    path = Path(directory) / name / "session.dpapi"
    return json.loads(
        win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 1)[1]
    )


def main():
    # The SDK configures root logging; request URLs may contain OAuth tickets.
    for name in ("httpx", "httpcore", "ngrok", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--garmin-python", type=Path, required=True)
    parser.add_argument("--garmin-data", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--garmin-port", type=int, default=8787)
    args = parser.parse_args()
    if not args.garmin_python.is_file():
        parser.error("Garmin interpreter does not exist")
    if (
        not all(1024 <= p <= 65535 for p in (args.port, args.garmin_port))
        or args.port == args.garmin_port
    ):
        parser.error("Use distinct unprivileged ports")
    saved = read_garmin_state(args.garmin_data, "remote-oauth")
    origin = public_origin(saved["origin"])
    credential = read_garmin_state(args.garmin_data, "remote-tunnel")
    os.environ.setdefault("MFP_BROWSER", "firefox")
    app, provider = create_gateway(origin, args.garmin_port, args.port)
    with provider.state():
        pass
    # Fail before opening ngrok if an existing service occupies either port.
    for port in (args.garmin_port, args.port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    env = dict(os.environ, GARMIN_MCP_DATA_DIR=str(args.garmin_data.absolute()))
    child = subprocess.Popen(
        [
            str(args.garmin_python),
            "-m",
            "garmin_connect_mcp.remote",
            "serve",
            "--public-url",
            origin,
            "--port",
            str(args.garmin_port),
        ],
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    listener = None
    listener_socket = None
    status = TokenStore(data_directory() / "gateway-status")
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            for _ in range(50):
                if child.poll() is not None:
                    raise RuntimeError("Garmin backend failed to start")
                try:
                    response = client.get(
                        f"http://127.0.0.1:{args.garmin_port}/.well-known/oauth-authorization-server/mcp/garmin-connect",
                        headers={"Host": urlsplit(origin).netloc},
                    )
                    if (
                        response.status_code == 200
                        and response.json()["issuer"].rstrip("/") == origin + "/mcp/garmin-connect"
                    ):
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Garmin backend did not become ready")
        import ngrok
        import uvicorn

        # Own the listening socket before forwarding to it.
        listener_socket = socket.socket()
        listener_socket.bind(("127.0.0.1", args.port))
        listener_socket.listen(128)
        listener = ngrok.forward(
            f"http://127.0.0.1:{args.port}",
            authtoken=credential["authtoken"],
            domain=urlsplit(origin).hostname,
        )
        if listener.url().rstrip("/") != origin:
            raise RuntimeError("ngrok returned an unexpected hostname")
        status.save(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "garmin_pid": child.pid,
                    "garmin_url": origin + "/mcp/garmin-connect/",
                    "myfitnesspal_url": origin + PREFIX + "/mcp",
                }
            )
        )
        print("Garmin: " + origin + "/mcp/garmin-connect/", flush=True)
        print("MyFitnessPal: " + origin + PREFIX + "/mcp", flush=True)
        config = uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            proxy_headers=False,
            limit_concurrency=16,
        )
        uvicorn.Server(config).run(sockets=[listener_socket])
    finally:
        if listener is not None:
            ngrok.disconnect(listener.url())
        if listener_socket is not None:
            listener_socket.close()
        if child.poll() is None:
            if os.name == "nt":
                # Windows venv launchers spawn a second interpreter process.
                subprocess.run(
                    ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        status.clear()


if __name__ == "__main__":
    main()
