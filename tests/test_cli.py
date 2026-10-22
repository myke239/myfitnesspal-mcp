import os
import sys

from myfitnesspal_mcp import cli
from myfitnesspal_mcp.service import AccessError, Service


def test_verify_browser_overrides_environment(monkeypatch, capsys):
    monkeypatch.setenv("MFP_BROWSER", "chrome")
    monkeypatch.setattr(
        sys, "argv", ["myfitnesspal-mcp", "verify", "--browser", "firefox"]
    )

    def verify(self):
        assert os.environ["MFP_BROWSER"] == "firefox"
        return {"connected": True}

    monkeypatch.setattr(cli.Service, "connection_status", verify)
    cli.main()
    assert '"connected": true' in capsys.readouterr().out


def test_safe_cookie_error_is_preserved():
    def fail():
        raise AccessError("Cannot read chrome cookies: use Firefox.")

    import pytest

    with pytest.raises(AccessError, match="use Firefox"):
        Service(fail).connection_status()
