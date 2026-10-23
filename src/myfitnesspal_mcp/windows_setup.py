"""Windows-only graphical installer assistant for MyFitnessPal MCP."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

URL = "https://www.myfitnesspal.com/account/login?callbackUrl=https%3A%2F%2Fwww.myfitnesspal.com%2Fmessages%2Fnew%2Flogin"
MARKETPLACE = "das-kreb-myfitnesspal"
PLUGIN = "myfitnesspal"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
        name: next((candidate for candidate in candidates if candidate.is_file()), None)
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


class SetupWizard:
    def __init__(self, root: tk.Tk, smoke_test: bool = False):
        self.root = root
        self.smoke_test = smoke_test
        self.app_dir = Path(sys.executable).resolve().parent
        self.codex = find_codex()
        self.browsers = installed_browsers()
        self.browser = tk.StringVar(
            value=next(iter(name for name in ("Firefox", "Chrome", "Edge") if name in self.browsers), "")
        )
        self.root.title("MyFitnessPal MCP Setup")
        self.root.geometry("720x500")
        self.root.minsize(650, 450)
        self.root.configure(background="#f4f7f7")
        self.root.resizable(False, False)
        icon = self.app_dir / "branding" / "das-kreb-logo.ico"
        if icon.is_file():
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.show("welcome")
        if smoke_test:
            self.root.withdraw()
            self.root.update()

    def show(self, name: str, detail: str = "") -> None:
        for child in self.root.winfo_children():
            child.destroy()
        page = tk.Frame(self.root, bg="#ffffff", padx=48, pady=34)
        page.pack(fill="both", expand=True, padx=22, pady=22)
        header = tk.Frame(page, bg="#ffffff")
        header.pack(fill="x")
        logo = self.app_dir / "branding" / "das-kreb-logo.png"
        if logo.is_file():
            try:
                from PIL import Image, ImageTk

                image = Image.open(logo)
                image.thumbnail((150, 46), Image.Resampling.LANCZOS)
                self.brand_image = ImageTk.PhotoImage(image)
                tk.Label(header, image=self.brand_image, bg="#ffffff").pack(side="left", anchor="w")
            except Exception:
                pass
        tk.Label(
            header,
            text="MYFITNESSPAL MCP",
            font=("Segoe UI", 10, "bold"),
            fg="#176b63",
            bg="#ffffff",
        ).pack(anchor="w")
        tk.Label(
            page,
            text={
                "welcome": "Welcome",
                "browser": "Choose your browser",
                "signin": "Sign in to MyFitnessPal",
                "working": "Setting up your connection",
                "retry": "One more step",
                "done": "You’re all set",
                "codex_missing": "Install Codex first",
            }.get(name, "MyFitnessPal MCP Setup"),
            font=("Segoe UI", 24, "bold"),
            fg="#172b2a",
            bg="#ffffff",
            wraplength=590,
            justify="left",
        ).pack(anchor="w", pady=(28, 12))
        body = {
            "welcome": "Connect MyFitnessPal to Codex in a few quick steps. Your password stays in your browser.",
            "browser": "Choose the browser where you use MyFitnessPal. We’ll open it for you.",
            "signin": f"Sign in to MyFitnessPal in {self.browser.get()}. When you’re done, return here and continue.",
            "working": detail or "Checking your sign-in and adding MyFitnessPal to Codex…",
            "retry": "We couldn’t finish setup. Follow the message below, then try again.",
            "done": "MyFitnessPal is installed in Codex. Close and reopen Codex, then start a new chat to use it.",
            "codex_missing": "Install Codex, then open MyFitnessPal MCP Setup from the Start menu to finish.",
        }.get(name, detail)
        tk.Label(
            page,
            text=body,
            font=("Segoe UI", 12),
            fg="#41504e",
            bg="#ffffff",
            wraplength=590,
            justify="left",
        ).pack(anchor="w", pady=(0, 16))
        if name == "browser":
            options = list(self.browsers)
            chooser = ttk.Combobox(
                page, textvariable=self.browser, values=options, state="readonly", width=20
            )
            chooser.pack(anchor="w", pady=(0, 8))
        if name == "signin":
            tk.Label(
                page,
                text="Enter your usual MyFitnessPal sign-in in the browser. This setup app never asks for or stores your password.",
                font=("Segoe UI", 10),
                fg="#667573",
                bg="#ffffff",
                wraplength=590,
                justify="left",
            ).pack(anchor="w", pady=(0, 10))
        if name == "working":
            progress = ttk.Progressbar(page, mode="indeterminate", length=420)
            progress.pack(anchor="w", pady=(8, 10))
            progress.start(12)
        if detail and name in {"retry", "codex_missing"}:
            detail_widget = tk.Label(
                page,
                text=detail,
                font=("Segoe UI", 10),
                fg="#8a3b32",
                bg="#ffffff",
                wraplength=590,
                justify="left",
            )
            detail_widget.pack(anchor="w", pady=(0, 8))
        buttons = {
            "welcome": ("Begin Install", self.begin),
            "browser": ("Open MyFitnessPal", self.open_mfp),
            "signin": ("I’m signed in — Continue", self.check_and_install),
            "retry": ("Try Again", self.check_and_install),
            "done": ("Finish", self.root.destroy),
            "codex_missing": ("Download Codex", self.open_codex_download),
        }
        if name in buttons:
            caption, command = buttons[name]
            action = tk.Button(
                page,
                text=caption,
                command=command,
                font=("Segoe UI", 11, "bold"),
                fg="#ffffff",
                bg="#176b63",
                activebackground="#12574f",
                activeforeground="#ffffff",
                relief="flat",
                padx=24,
                pady=12,
                cursor="hand2",
            )
            action.pack(anchor="w", side="bottom", pady=(18, 0))
        footer = tk.Label(
            page,
            text="No administrator access required  •  Das Kreb",
            font=("Segoe UI", 9),
            fg="#889492",
            bg="#ffffff",
        )
        footer.pack(anchor="w", side="bottom", pady=(0, 2))

    def begin(self) -> None:
        if not self.codex:
            self.show("codex_missing")
        elif not self.browsers:
            self.show("retry", "Install Firefox, Chrome, or Edge, then reopen setup.")
        else:
            self.show("browser")

    def open_mfp(self) -> None:
        browser_path = self.browsers.get(self.browser.get())
        if not browser_path:
            self.show("retry", "Select an installed browser to continue.")
            return
        try:
            subprocess.Popen(
                [str(browser_path), URL],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            webbrowser.open(URL)
        self.show("signin")

    def check_and_install(self) -> None:
        if self.smoke_test:
            self.show("done")
            return
        if not self.codex or not self.browser.get():
            self.show("retry", "Codex or a supported browser could not be found. Rerun setup after installing it.")
            return
        self.show("working")

        def work() -> None:
            executable = self.app_dir / "myfitnesspal-mcp.exe"
            try:
                result = subprocess.run(
                    [str(executable), "verify", "--browser", self.browser.get().lower()],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    creationflags=CREATE_NO_WINDOW,
                )
                if result.returncode:
                    raise RuntimeError(
                        "No signed-in MyFitnessPal session was found. Sign in in your browser and try again."
                    )
                prepare_and_install(self.codex, self.app_dir, self.browser.get())
            except Exception as error:
                message = str(error) if isinstance(error, RuntimeError) else "Setup could not finish. Check your internet connection and try again."
                self.root.after(0, lambda: self.show("retry", message))
            else:
                self.root.after(0, lambda: self.show("done"))

        threading.Thread(target=work, daemon=True).start()

    def open_codex_download(self) -> None:
        webbrowser.open("https://developers.openai.com/codex/quickstart")


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
    SetupWizard(root, smoke_test=args.smoke_test)
    if args.smoke_test:
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
