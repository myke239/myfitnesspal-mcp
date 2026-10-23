"""Windows owner-only encrypted remote state, separate from browser credentials."""

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def data_directory():
    if getattr(sys, "frozen", False) and os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is required for Windows remote state")
        return Path(local_app_data) / "DasKreb" / "MyFitnessPalMCP" / "remote"
    return Path(__file__).absolute().parents[2] / "work" / "remote"


def _is_junction(path: Path) -> bool:
    check = getattr(path, "is_junction", None)
    return check is not None and check()


def restrict(path: Path) -> None:
    if path.is_symlink() or _is_junction(path):
        raise ValueError("Session paths cannot be symlinks")
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    acl = win32security.ACL()
    flags = (
        win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE
        if path.is_dir()
        else 0
    )
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION, flags, win32con.GENERIC_ALL, sid
    )
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION,
        flags,
        win32con.GENERIC_ALL,
        win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )


class TokenStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_directory()
        self.path = self.directory / (
            "session.dpapi" if os.name == "nt" else "session.json"
        )

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, tokens: str) -> None:
        json.loads(tokens)
        self.directory.mkdir(parents=True, exist_ok=True)
        restrict(self.directory)
        raw = tokens.encode("utf-8")
        if os.name == "nt":
            import win32crypt

            raw = win32crypt.CryptProtectData(
                raw, "MyFitnessPal MCP", None, None, None, 1
            )
        else:
            raise RuntimeError(
                "Remote credential storage currently requires Windows DPAPI"
            )
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix="session-")
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            restrict(temporary_path)
            if self.path.is_symlink() or _is_junction(self.path):
                raise ValueError("Session paths cannot be symlinks")
            temporary_path.replace(self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def load(self) -> str:
        restrict(self.directory)
        restrict(self.path)
        raw = self.path.read_bytes()
        if os.name == "nt":
            import win32crypt

            raw = win32crypt.CryptUnprotectData(raw, None, None, None, 1)[1]
        else:
            raise RuntimeError(
                "Remote credential storage currently requires Windows DPAPI"
            )
        tokens = raw.decode("utf-8")
        json.loads(tokens)
        return tokens

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


@contextlib.contextmanager
def session_lock(store):
    store.directory.mkdir(parents=True, exist_ok=True)
    restrict(store.directory)
    lockpath = store.directory / "request.lock"
    if lockpath.is_symlink() or _is_junction(lockpath):
        raise ValueError("Unsafe lock path")
    with lockpath.open("a+b") as lock:
        restrict(lockpath)
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        started = time.monotonic()
        while True:
            try:
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - started > 30:
                    raise TimeoutError("Credential store busy") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


