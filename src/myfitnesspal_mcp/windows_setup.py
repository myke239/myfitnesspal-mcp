"""Windows setup wizard for the MyFitnessPal MCP connector."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlsplit

from . import __version__
from .remote import (
    READ_SCOPE,
    WRITE_SCOPE,
    OwnerProvider,
    public_origin,
    valid_callback,
)
from .storage import TokenStore, data_directory

URL = "https://www.myfitnesspal.com/account/login?callbackUrl=https%3A%2F%2Fwww.myfitnesspal.com%2Fmessages%2Fnew%2Flogin"
CHATGPT_URL = "https://chatgpt.com/plugins"
MARKETPLACE = "das-kreb-myfitnesspal"
PLUGIN = "myfitnesspal"
MFP_RESOURCE = "/mcp/myfitnesspal"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)

PAGES = {
    "welcome": (
        "Install MyFitnessPal MCP",
        "Connect your MyFitnessPal account to ChatGPT or Codex. Setup will guide you through each step.",
    ),
    "signin": (
        "Connect your MyFitnessPal account",
        "Choose the browser where you use MyFitnessPal. Your password stays in your browser.",
    ),
    "verify": (
        "Verify MyFitnessPal",
        "Return here after signing in. Setup will check your browser session before continuing.",
    ),
    "client": ("Where will you use MyFitnessPal?", "Choose the app you want to connect."),
    "codex": (
        "Connect Codex",
        "Setup will install the MyFitnessPal plugin and check its tools.",
    ),
    "hosting": (
        "Set up your ChatGPT connection",
        "Use the same HTTPS address as your other MCP connectors, with the MyFitnessPal path.",
    ),
    "server": (
        "Start the shared MCP server",
        "Setup replaces Garmin’s separate tunnel with one shared gateway. Existing grants stay in place; Garmin uses /mcp/garmin-connect and MyFitnessPal uses /mcp/myfitnesspal.",
    ),
    "existing": (
        "Use your existing HTTPS address",
        "Enter the address of a running MyFitnessPal shared gateway. The MCP path is added for you.",
    ),
    "chatgpt": (
        "Add MyFitnessPal in ChatGPT",
        "In Plugins, choose Add custom MCP server. Enter the details below and start the connection.",
    ),
    "request": (
        "Review your connection request",
        "Start connecting MyFitnessPal in ChatGPT. Copy the connection code from the browser approval page and paste it here.",
    ),
    "review": (
        "Approve your connection",
        "Review the requested access. Approve only the ChatGPT connection you just started.",
    ),
    "confirm": (
        "Finish connecting in ChatGPT",
        "Return to ChatGPT, choose Continue, then install the connector. Come back here to verify it.",
    ),
    "finish": (
        "You’re connected",
        "MyFitnessPal sign-in and the connection passed verification. Start a new chat to use it.",
    ),
}


def find_codex() -> str | None:
    """Find the Codex CLI, including the per-user desktop-app installation."""
    found = shutil.which("codex.exe") or shutil.which("codex")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = sorted(
        (local / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def installed_browsers() -> dict[str, Path]:
    """Return supported browsers installed for the current Windows user."""
    roots = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local")),
    ]
    paths = {
        "Firefox": [root / "Mozilla Firefox" / "firefox.exe" for root in roots],
        "Chrome": [
            root / "Google" / "Chrome" / "Application" / "chrome.exe"
            for root in roots
        ],
        "Edge": [
            root / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            for root in roots
        ],
    }
    return {
        name: next(candidate for candidate in candidates if candidate.is_file())
        for name, candidates in paths.items()
        if any(candidate.is_file() for candidate in candidates)
    }


def _run_codex(codex: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [codex, *args, "--json"],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=CREATE_NO_WINDOW,
    )


def prepare_and_install(codex: str, app_dir: Path, browser: str) -> None:
    """Wire the installed executable into the local plugin, then install it."""
    plugin_dir = app_dir / "marketplace" / "plugins" / PLUGIN
    manifest_path = plugin_dir / ".mcp.json"
    marketplace_file = app_dir / "marketplace" / ".agents" / "plugins" / "marketplace.json"
    if not manifest_path.is_file() or not marketplace_file.is_file():
        raise RuntimeError("The installed plugin files are incomplete. Rerun the installer.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    servers = manifest.get("mcpServers", {})
    if PLUGIN not in servers:
        raise RuntimeError("The MyFitnessPal plugin configuration is incomplete. Rerun the installer.")
    servers[PLUGIN]["command"] = str(app_dir / "myfitnesspal-mcp.exe")
    servers[PLUGIN]["args"] = ["serve"]
    servers[PLUGIN]["env"] = {"MFP_BROWSER": browser.lower()}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    add_marketplace = _run_codex(
        codex, ["plugin", "marketplace", "add", str(plugin_dir.parent.parent)]
    )
    if add_marketplace.returncode:
        raise RuntimeError("Codex could not add the MyFitnessPal plugin source.")
    install = _run_codex(codex, ["plugin", "add", f"{PLUGIN}@{MARKETPLACE}"])
    if install.returncode:
        raise RuntimeError("Codex could not install the MyFitnessPal plugin.")


def remove_plugin(codex: str) -> None:
    """Remove this install's Codex plugin and its local marketplace source."""
    _run_codex(codex, ["plugin", "remove", f"{PLUGIN}@{MARKETPLACE}"])
    _run_codex(codex, ["plugin", "marketplace", "remove", MARKETPLACE])


def verification_failure(browser: str, output: str) -> str:
    """Turn the verifier's sanitized error into a useful setup instruction."""
    detail = output.strip()
    if browser.lower() in {"chrome", "edge"}:
        advice = (
            f"Windows may be blocking access to {browser}'s saved cookies. "
            "If you are signed in there, try Firefox: sign in to MyFitnessPal "
            "in Firefox, return here, choose Firefox, and continue."
        )
    else:
        advice = (
            f"Make sure you are signed in to MyFitnessPal in the selected "
            f"{browser} profile, then try again."
        )
    if detail:
        return f"Could not verify your sign-in in {browser}.\n\n{detail}\n\n{advice}"
    return f"Could not verify your sign-in in {browser}. {advice}"


def _fingerprint(pending: dict) -> str:
    return hashlib.sha256(
        json.dumps([pending["client_id"], pending["params"]], sort_keys=True).encode()
    ).hexdigest()


def review_connection(origin: str, ticket: str, started_at: float, directory=None) -> dict:
    """Return a safe review of a fresh MyFitnessPal OAuth request."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", ticket):
        raise RuntimeError("Paste the connection code shown in your browser.")
    provider = OwnerProvider(
        origin, directory=directory, prefix="/myfitnesspal", resource_path=MFP_RESOURCE
    )
    with provider.state() as state:
        pending = state["pending"].get(ticket)
        if not pending or pending["approved"] or pending["expires_at"] <= time.time():
            raise RuntimeError("This code was not found or has expired. Restart the connection in ChatGPT.")
        params = pending["params"]
        scopes = params.get("scopes", [])
        if (
            pending["expires_at"] - 300 < started_at
            or params.get("resource") != provider.resource
            or not valid_callback(params.get("redirect_uri", ""))
            or READ_SCOPE not in scopes
            or not set(scopes) <= {READ_SCOPE, WRITE_SCOPE}
        ):
            raise RuntimeError("This code is not a valid MyFitnessPal connection request. Start again in ChatGPT.")
        return {
            "ticket": ticket,
            "client_id": pending["client_id"],
            "callback": params["redirect_uri"],
            "scopes": list(scopes),
            "resource": provider.resource,
            "fingerprint": _fingerprint(pending),
        }


def approve_connection(origin: str, review: dict, directory=None) -> None:
    """Approve only the exact OAuth request shown in the local review page."""
    provider = OwnerProvider(
        origin, directory=directory, prefix="/myfitnesspal", resource_path=MFP_RESOURCE
    )
    with provider.state() as state:
        pending = state["pending"].get(review["ticket"])
        if (
            not pending
            or pending["approved"]
            or pending["expires_at"] <= time.time()
            or pending["params"].get("resource") != provider.resource
            or _fingerprint(pending) != review["fingerprint"]
        ):
            raise RuntimeError("This request changed or expired. Restart the connection in ChatGPT.")
        pending["approved"] = True


class Backend:
    """Local operations used by the page-based setup wizard."""

    def __init__(self, app_dir: Path | None = None):
        self.app_dir = app_dir or Path(sys.executable).resolve().parent
        self.executable = self.app_dir / "myfitnesspal-mcp.exe"
        self.data_dir = data_directory()
        self.started_at = time.time()
        self.origin = ""
        self.server_url = ""
        self.review = None

    def verify(self, browser: str) -> None:
        result = subprocess.run(
            [str(self.executable), "verify", "--browser", browser.lower()],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise RuntimeError(verification_failure(browser, result.stderr or result.stdout))

    def connect_codex(self, codex: str, browser: str) -> None:
        self.verify(browser)
        prepare_and_install(codex, self.app_dir, browser)

    @staticmethod
    def _garmin_installation() -> tuple[Path, Path]:
        """Find the existing Garmin runtime and its private data folder."""
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        root = local / "Programs" / "GarminConnectMCP"
        receipt = root / "installation.json"
        data_candidates = [
            Path(os.environ["GARMIN_MCP_DATA_DIR"]).expanduser()
            if os.environ.get("GARMIN_MCP_DATA_DIR")
            else None,
            Path("D:/developer/.garmin-connect-mcp"),
            local / "garmin-connect-mcp",
        ]
        data = next(
            (
                path
                for path in data_candidates
                if path and (path / "remote-tunnel" / "session.dpapi").is_file()
            ),
            None,
        )
        if data is None or not receipt.is_file():
            raise RuntimeError("Install and connect Garmin Connect before setting up the shared HTTPS address.")
        metadata = json.loads(receipt.read_text(encoding="utf-8"))
        runtime = Path(metadata.get("launcher", metadata.get("python", "")))
        try:
            resolved_root = root.resolve(strict=True)
            resolved_runtime = runtime.resolve(strict=True)
        except OSError:
            raise RuntimeError("The Garmin Connect runtime could not be found. Repair its installation and try again.") from None
        if (
            runtime.is_symlink()
            or not resolved_runtime.is_file()
            or resolved_root not in resolved_runtime.parents
            or resolved_runtime.name.lower() != "garmin-connect.exe"
        ):
            raise RuntimeError("The Garmin Connect runtime could not be found. Repair its installation and try again.")
        for name in ("remote-tunnel", "remote-oauth"):
            if not (data / name / "session.dpapi").is_file():
                raise RuntimeError("Finish Garmin's HTTPS setup before adding another connector.")
        return resolved_runtime, data.resolve()

    def start_shared_gateway(self, browser: str) -> str:
        """Start the shared Garmin/MyFitnessPal gateway on Garmin's HTTPS origin."""
        if os.name != "nt":
            raise RuntimeError("The shared HTTPS gateway setup is currently available on Windows.")
        runtime, garmin_data = self._garmin_installation()
        status = TokenStore(self.data_dir / "gateway-status")
        if status.exists():
            try:
                running = json.loads(status.load())
                if running.get("pid") and running.get("myfitnesspal_url"):
                    os.kill(int(running["pid"]), 0)
                    self.server_url = running["myfitnesspal_url"]
                    parts = urlsplit(self.server_url)
                    self.origin = public_origin(f"{parts.scheme}://{parts.netloc}")
                    return self.check_server(self.origin)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                status.clear()

        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/MyFitnessPalMCPGateway.vbs"
        marker = "MyFitnessPal MCP shared gateway"
        if startup.exists() and marker not in startup.read_text(encoding="utf-8"):
            raise RuntimeError("A different startup app already uses the MyFitnessPal gateway entry. Remove it before continuing.")

        # The packaged Windows executable may hand off to a detached server
        # process, so its DPAPI status file is not always available to a later
        # installer run. Reuse a gateway that already answers on Garmin's saved
        # HTTPS origin instead of starting a second copy on occupied ports.
        try:
            saved = json.loads(TokenStore(garmin_data / "remote-oauth").load())
            origin = public_origin(saved["origin"])
            url = self.check_server(origin)
            self._install_startup(startup, marker, runtime, garmin_data)
            return url
        except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError):
            pass

        stop = subprocess.run(
            [str(runtime), "background-stop"], capture_output=True, timeout=40,
            creationflags=CREATE_NO_WINDOW,
        )
        if stop.returncode:
            raise RuntimeError("Garmin's existing tunnel could not be paused. Close Garmin setup and try again.")
        remove_startup = subprocess.run(
            [str(runtime), "background-uninstall"], capture_output=True, timeout=40,
            creationflags=CREATE_NO_WINDOW,
        )
        if remove_startup.returncode:
            subprocess.run([str(runtime), "background-start"], capture_output=True, timeout=40, creationflags=CREATE_NO_WINDOW)
            raise RuntimeError("Garmin's old tunnel startup could not be changed. Try again after updating Garmin Connect MCP.")

        env = dict(os.environ, MFP_BROWSER=browser.lower())
        process = None
        process = subprocess.Popen(
            [str(self.executable), "gateway", "--garmin-executable", str(runtime), "--garmin-data", str(garmin_data)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, creationflags=DETACHED,
        )
        try:
            exited_at = None
            for _ in range(120):
                if status.exists():
                    running = json.loads(status.load())
                    self.server_url = running.get("myfitnesspal_url", "")
                    if self.server_url:
                        parts = urlsplit(self.server_url)
                        self.origin = public_origin(f"{parts.scheme}://{parts.netloc}")
                        self.check_server(self.origin)
                        self._install_startup(startup, marker, runtime, garmin_data)
                        return self.server_url
                if process.poll() is not None:
                    exited_at = exited_at or time.monotonic()
                    if time.monotonic() - exited_at >= 10:
                        raise RuntimeError("The shared MCP server could not start. Check the saved ngrok address and try again.")
                else:
                    exited_at = None
                time.sleep(0.5)
            raise RuntimeError("The shared MCP server is still starting. Wait a moment, then try again.")
        except Exception:
            if process is not None and process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=CREATE_NO_WINDOW,
                )
            subprocess.run([str(runtime), "background-install"], capture_output=True, timeout=40, creationflags=CREATE_NO_WINDOW)
            subprocess.run([str(runtime), "background-start"], capture_output=True, timeout=40, creationflags=CREATE_NO_WINDOW)
            raise

    def _install_startup(self, path: Path, marker: str, runtime: Path, data: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        command = subprocess.list2cmdline(
            [str(self.executable), "gateway", "--garmin-executable", str(runtime), "--garmin-data", str(data)]
        ).replace('"', '""')
        path.write_text(
            "' " + marker + "\nCreateObject(\"WScript.Shell\").Run \"" + command + "\", 0, False\n",
            encoding="utf-8",
        )

    def check_server(self, value: str) -> str:
        """Check that the entered HTTPS origin serves this MCP resource."""
        import ssl

        import httpx
        import truststore

        try:
            origin = public_origin(value.strip())
            resource = origin + MFP_RESOURCE
            metadata_url = origin + "/.well-known/oauth-protected-resource" + MFP_RESOURCE
            issuer = origin + "/myfitnesspal"
            with httpx.Client(
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                timeout=15,
                follow_redirects=False,
                headers={"ngrok-skip-browser-warning": "true"},
            ) as client:
                metadata = client.get(metadata_url)
                guard = client.post(resource, json={})
            value = metadata.json()
            if (
                metadata.status_code != 200
                or value.get("resource") != resource
                or value.get("authorization_servers") != [issuer]
                or guard.status_code != 401
            ):
                raise ValueError("Unexpected MCP server")
            self.origin, self.server_url = origin, resource
            return resource
        except Exception:
            raise RuntimeError("The MyFitnessPal server is not ready at this address. Keep the shared gateway running and check the HTTPS address.") from None

    def review_request(self, ticket: str) -> dict:
        self.review = review_connection(self.origin, ticket.strip(), self.started_at)
        return self.review

    def approve(self) -> None:
        if not self.review:
            raise RuntimeError("Review the connection request first.")
        approve_connection(self.origin, self.review)

    def verify_chatgpt(self) -> None:
        import ssl

        import httpx
        import truststore

        if not self.review:
            raise RuntimeError("Approve the connection request first.")
        provider = OwnerProvider(
            self.origin, prefix="/myfitnesspal", resource_path=MFP_RESOURCE
        )
        with provider.state() as state:
            grants = [
                token
                for token in state["access"].values()
                if token["client_id"] == self.review["client_id"]
                and token["expires_at"] > time.time()
                and token["resource"] == provider.resource
                and READ_SCOPE in token["scopes"]
            ]
        if not grants:
            raise RuntimeError("Return to ChatGPT, select Continue, and install the connector. Then check again.")
        try:
            with httpx.Client(
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                timeout=25,
                follow_redirects=False,
                headers={
                    "ngrok-skip-browser-warning": "true",
                    "Authorization": "Bearer " + grants[0]["token"],
                    "Accept": "application/json, text/event-stream",
                },
            ) as client:
                response = client.post(
                    provider.resource,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
                result = response.json()
            if response.status_code != 200 or not result.get("result", {}).get("tools"):
                raise ValueError("Tool discovery failed")
        except Exception:
            raise RuntimeError("ChatGPT authorization exists, but the server did not pass its tool check. Check the connection and try again.") from None


class SetupWizard:
    """Page-based setup UI using the same layout and step language as Garmin."""

    def __init__(self, root: tk.Tk, smoke_test: bool = False, backend: Backend | None = None):
        self.root = root
        self.smoke_test = smoke_test
        self.backend = backend or Backend()
        self.events = queue.Queue()
        self.busy = False
        self.history: list[str] = []
        self.page = ""
        self.client = tk.StringVar(value="chatgpt")
        self.hosting = tk.StringVar(value="shared")
        self.browser = tk.StringVar(value=next(iter(name for name in ("Firefox", "Chrome", "Edge") if name in installed_browsers()), ""))
        self.browsers = installed_browsers()
        self.origin = tk.StringVar(value="")
        root.title("MyFitnessPal MCP Setup")
        root.geometry("760x560")
        root.minsize(700, 520)
        root.resizable(True, True)
        icon = self.backend.app_dir / "branding" / "das-kreb-logo.ico"
        if icon.is_file():
            try:
                root.iconbitmap(str(icon))
            except tk.TclError:
                pass

        style = ttk.Style(root)
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Body.TLabel", font=("Segoe UI", 11))
        style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(20, 10))
        style.configure("Brand.TLabel", font=("Segoe UI", 10, "bold"))
        outer = ttk.Frame(root, padding=28)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="MYFITNESSPAL MCP", style="Brand.TLabel").pack(anchor="w")
        self.step = ttk.Label(outer, foreground="#526278")
        self.step.pack(anchor="w", pady=(8, 16))
        self.title = ttk.Label(outer, style="Title.TLabel", wraplength=680)
        self.title.pack(anchor="w")
        self.description = ttk.Label(outer, style="Body.TLabel", wraplength=680, justify="left")
        self.description.pack(anchor="w", pady=(12, 18))
        self.content = ttk.Frame(outer)
        self.content.pack(fill="both", expand=True)
        self.message = ttk.Label(outer, foreground="#ad2634", wraplength=680)
        self.message.pack(anchor="w", pady=(8, 12))
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", side="bottom")
        self.back = ttk.Button(buttons, text="Back", command=self.go_back)
        self.back.pack(side="left")
        self.primary = ttk.Button(buttons, style="Primary.TButton")
        self.primary.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.bind("<Return>", lambda _event: self.primary.invoke())
        root.after(80, self.drain)
        self.show_page("welcome", remember=False)
        if smoke_test:
            root.withdraw()
            root.update()

    def field(self, label: str, variable=None, readonly=False, secret=False):
        ttk.Label(self.content, text=label, style="Body.TLabel").pack(anchor="w", pady=(6, 4))
        entry = ttk.Entry(self.content, width=68, textvariable=variable, show="•" if secret else "")
        entry._textvariable = variable
        entry.pack(fill="x", pady=(0, 10))
        if readonly:
            entry.configure(state="readonly")
        return entry

    def button(self, text: str, action) -> None:
        self.primary.configure(text=text, command=action, state="normal")

    def show_page(self, name: str, remember=True, detail: str = "") -> None:
        if remember and self.page and name != self.page:
            self.history.append(self.page)
        self.page = name
        self.busy = False
        self.progress.stop()
        self.progress.pack_forget()
        for child in self.content.winfo_children():
            child.destroy()
        self.message.configure(text="")
        self.back.configure(state="normal" if self.history and name not in {"review", "confirm", "finish"} else "disabled")
        title, description = PAGES.get(name, ("MyFitnessPal MCP Setup", detail))
        self.title.configure(text=title)
        self.description.configure(text=description)
        self.step.configure(text="Setup / " + __version__ if name == "welcome" else "MyFitnessPal setup / " + title)
        self.render(name, detail)

    def render(self, name: str, detail: str = "") -> None:
        if name == "welcome":
            self.button("Begin Install", lambda: self.show_page("signin"))
        elif name == "signin":
            options = list(self.browsers)
            chooser = ttk.Combobox(self.content, textvariable=self.browser, values=options, state="readonly", width=28)
            chooser.pack(anchor="w", pady=(0, 8))
            self.button("Open MyFitnessPal", self.open_mfp)
        elif name == "verify":
            ttk.Label(self.content, text="Choose the browser where you just signed in.", style="Body.TLabel").pack(anchor="w")
            self.button("Verify MyFitnessPal", lambda: self.task(lambda: self.backend.verify(self.browser.get()), lambda _value: self.show_page("client")))
        elif name == "client":
            for label, value in (("ChatGPT (including phone access)", "chatgpt"), ("Codex", "codex")):
                ttk.Radiobutton(self.content, text=label, value=value, variable=self.client).pack(anchor="w", pady=12)
            self.button("Next", self.choose_client)
        elif name == "codex":
            self.button("Connect Codex", self.connect_codex)
        elif name == "hosting":
            choices = (
                ("Start the shared gateway on my Garmin HTTPS address", "shared"),
                ("Use a running MyFitnessPal HTTPS address", "existing"),
            )
            for label, value in choices:
                ttk.Radiobutton(self.content, text=label, value=value, variable=self.hosting).pack(anchor="w", pady=12)
            self.button("Next", lambda: self.show_page("server" if self.hosting.get() == "shared" else "existing"))
        elif name == "server":
            self.button("Start shared server", lambda: self.task(lambda: self.backend.start_shared_gateway(self.browser.get()), self.server_ready))
        elif name == "existing":
            self.field("HTTPS address (origin only, for example https://your-ngrok-host)", variable=self.origin)
            self.button("Check connection", lambda: self.task(lambda: self.backend.check_server(self.origin.get()), self.server_ready))
        elif name == "chatgpt":
            ttk.Label(self.content, text="Name: MyFitnessPal\nAuthentication: OAuth / Dynamic Client Registration", style="Body.TLabel").pack(anchor="w", pady=(0, 8))
            self.field("Server URL", variable=tk.StringVar(value=self.backend.server_url), readonly=True)
            self.button("Copy URL and open ChatGPT", self.open_chatgpt)
        elif name == "request":
            self.ticket = self.field("Connection code from the browser")
            self.button("Review request", lambda: self.task(lambda: self.backend.review_request(self.ticket.get()), lambda value: self.show_page("review", detail=value)))
        elif name == "review":
            review = detail if isinstance(detail, dict) else self.backend.review
            scopes = "Read and modify MyFitnessPal data" if WRITE_SCOPE in review["scopes"] else "Read MyFitnessPal data"
            ttk.Label(self.content, text=scopes, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 12))
            ttk.Label(self.content, text="Server: " + review["resource"] + "\nCallback: " + review["callback"] + "\nClient: " + review["client_id"], wraplength=660).pack(anchor="w")
            self.button("Approve connection", lambda: self.task(self.backend.approve, lambda _value: self.show_page("confirm")))
        elif name == "confirm":
            self.button("Verify connection", lambda: self.task(self.backend.verify_chatgpt, lambda _value: self.show_page("finish")))
        elif name == "finish":
            connected = "ChatGPT connection verified" if self.client.get() == "chatgpt" else "Codex plugin installed"
            ttk.Label(self.content, text="✓ MyFitnessPal account verified\n✓ MCP server tools verified\n✓ " + connected, style="Body.TLabel").pack(anchor="w", pady=8)
            self.button("Close", self.root.destroy)
        elif name == "retry":
            ttk.Label(self.content, text=detail, foreground="#ad2634", wraplength=660).pack(anchor="w")
            self.button("Try Again", self.go_back)

    def open_mfp(self) -> None:
        browser_path = self.browsers.get(self.browser.get())
        if not browser_path:
            self.show_page("retry", detail="Install Firefox, Chrome, or Edge, then reopen setup.")
            return
        try:
            subprocess.Popen([str(browser_path), URL], creationflags=CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            webbrowser.open(URL)
        self.show_page("verify")

    def choose_client(self) -> None:
        if self.client.get() == "codex":
            self.show_page("codex")
        else:
            self.show_page("hosting")

    def connect_codex(self) -> None:
        codex = find_codex()
        if not codex:
            self.show_page("retry", detail="Install Codex, then reopen MyFitnessPal MCP Setup from the Start menu.")
            return
        self.task(lambda: self.backend.connect_codex(codex, self.browser.get()), lambda _value: self.show_page("finish"))

    def server_ready(self, url: str) -> None:
        self.backend.server_url = url
        self.show_page("chatgpt")

    def open_chatgpt(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.backend.server_url)
        webbrowser.open(CHATGPT_URL)
        self.show_page("request")

    def task(self, work, done) -> None:
        if self.busy:
            return
        self.busy = True
        self.message.configure(text="Working…")
        self.primary.configure(state="disabled")
        self.back.configure(state="disabled")
        self.progress.pack(fill="x", before=self.primary.master, pady=(0, 10))
        self.progress.start()

        def run():
            try:
                self.events.put(("done", (done, work())))
            except Exception as error:
                message = str(error) if isinstance(error, RuntimeError) else "This step could not finish. Check your connection, then try again."
                self.events.put(("error", message))

        threading.Thread(target=run, daemon=True).start()

    def drain(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "done":
                    callback, result = value
                    callback(result)
                else:
                    self.show_page("retry", detail=value)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(80, self.drain)

    def go_back(self) -> None:
        if not self.busy and self.history:
            self.show_page(self.history.pop(), remember=False)


def main() -> None:
    if os.name != "nt":
        raise SystemExit("The graphical setup app is available on Windows only.")
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args, _ = parser.parse_known_args()
    if args.uninstall:
        codex = find_codex()
        if codex:
            remove_plugin(codex)
        return
    root = tk.Tk()
    wizard = SetupWizard(root, smoke_test=args.smoke_test)
    if args.smoke_test:
        wizard.backend.server_url = "https://example.invalid/mcp/myfitnesspal"
        review = {
            "scopes": [READ_SCOPE],
            "resource": "https://example.invalid/mcp/myfitnesspal",
            "callback": "https://chatgpt.com/connector/oauth/test",
            "client_id": "smoke-test-client",
        }
        for page in PAGES:
            wizard.show_page(
                page,
                remember=False,
                detail=review if page == "review" else "",
            )
            root.update_idletasks()
            if not wizard.primary["text"]:
                raise RuntimeError(f"Setup page has no primary action: {page}")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
