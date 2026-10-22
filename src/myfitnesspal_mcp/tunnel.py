"""Run the personal OAuth service through the official ngrok SDK."""

import argparse
import getpass
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .remote import create_http_app
from .storage import TokenStore, data_directory


def validate_domain(domain, excluded_domain=None):
    if not domain or any(c in domain for c in "/:@ \r\n") or "." not in domain:
        raise ValueError("Supply --domain with a distinct reserved ngrok hostname.")
    if domain.lower().rstrip(".") == (excluded_domain or "").lower().rstrip("."):
        raise ValueError(
            "That hostname belongs to Garmin. Reserve a separate ngrok hostname."
        )
    return domain.lower().rstrip(".")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "run", "status"])
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument(
        "--domain", help="A distinct ngrok hostname reserved for MyFitnessPal."
    )
    parser.add_argument(
        "--reuse-garmin-data",
        type=Path,
        help="Garmin data directory: copy only its encrypted ngrok credential, never OAuth grants.",
    )
    args = parser.parse_args()
    store = TokenStore(data_directory() / "remote-tunnel")
    status = TokenStore(data_directory() / "remote-status")
    if args.command == "setup":
        if args.reuse_garmin_data:
            source = TokenStore(args.reuse_garmin_data / "remote-tunnel")
            if not source.exists():
                raise SystemExit("No saved Garmin ngrok credential at that directory.")
            if os.name != "nt":
                raise SystemExit(
                    "Saved credential reuse currently requires Windows DPAPI."
                )
            import win32crypt

            # Read only: do not change Garmin's files, permissions or OAuth state.
            value = json.loads(
                win32crypt.CryptUnprotectData(
                    source.path.read_bytes(), None, None, None, 1
                )[1].decode("utf-8")
            )
            token = value.get("authtoken")
            if (
                not isinstance(token, str)
                or not token
                or any(c.isspace() for c in token)
            ):
                raise SystemExit("Invalid saved ngrok credential.")
            excluded_domain = None
            for name in ("remote-status", "remote-oauth"):
                other = TokenStore(args.reuse_garmin_data / name)
                if other.exists():
                    saved = json.loads(
                        win32crypt.CryptUnprotectData(
                            other.path.read_bytes(), None, None, None, 1
                        )[1].decode("utf-8")
                    )
                    excluded_domain = urlsplit(
                        saved.get("url") or saved.get("origin") or ""
                    ).hostname
                    if excluded_domain:
                        break
            store.save(
                json.dumps({"authtoken": token, "excluded_domain": excluded_domain})
            )
            print(
                "Saved a separately encrypted copy of the existing ngrok account credential."
            )
            return
        if not sys.stdin.isatty():
            raise SystemExit(
                "Run setup in your own terminal so the token stays private."
            )
        token = getpass.getpass("Paste your ngrok authtoken (hidden): ").strip()
        if not token or any(character.isspace() for character in token):
            raise SystemExit("Expected a single ngrok authtoken")
        store.save(json.dumps({"authtoken": token}))
        print(
            "Tunnel token saved with "
            + (
                "Windows account encryption."
                if os.name == "nt"
                else "owner-only file permissions."
            )
        )
        return
    if args.command == "status":
        print(status.load() if status.exists() else "Tunnel has not started.")
        return
    if not store.exists():
        raise SystemExit("Run python -m myfitnesspal_mcp.tunnel setup first.")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Use an unprivileged local port")
    saved = json.loads(store.load())
    try:
        domain = validate_domain(args.domain, saved.get("excluded_domain"))
    except ValueError as error:
        raise SystemExit(str(error)) from None
    import ngrok
    import uvicorn

    # Reserve the port before forwarding; never expose another local process.
    listener_socket = socket.socket()
    listener_socket.bind(("127.0.0.1", args.port))
    listener_socket.listen(128)
    listener = None
    try:
        listener = ngrok.forward(
            f"http://127.0.0.1:{args.port}",
            authtoken=saved["authtoken"],
            domain=domain,
        )
        origin = listener.url()
        os.environ.setdefault("MFP_BROWSER", "firefox")
        app, provider = create_http_app(origin, args.port)
        with provider.state():
            pass
        status.save(
            json.dumps({"url": origin + "/mcp", "pid": os.getpid(), "port": args.port})
        )
        print("Authenticated MyFitnessPal MCP: " + origin + "/mcp", flush=True)
        config = uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            proxy_headers=False,
            timeout_keep_alive=5,
            limit_concurrency=16,
        )
        uvicorn.Server(config).run(sockets=[listener_socket])
    finally:
        if listener is not None:
            ngrok.disconnect(listener.url())
        listener_socket.close()
        status.clear()


if __name__ == "__main__":
    main()
