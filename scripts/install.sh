#!/usr/bin/env bash
set -euo pipefail
REPO="myke239/myfitnesspal-mcp"
VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"; fi
VERSION="${VERSION#v}"
BASE="https://github.com/$REPO/releases/download/v$VERSION"
ROOT="${MFP_INSTALL_DIR:-$HOME/.local/share/myfitnesspal-mcp}"
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "Python 3.11+ is required." >&2; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or newer is required"' || exit 1
mkdir -p "$ROOT"
WHEEL="myfitnesspal_mcp-${VERSION}-py3-none-any.whl"
curl -fL "$BASE/$WHEEL" -o "$ROOT/$WHEEL"
"$PYTHON" -m venv "$ROOT/venv"
"$ROOT/venv/bin/python" -m pip install --upgrade pip
"$ROOT/venv/bin/python" -m pip install "$ROOT/$WHEEL"
cat > "$ROOT/myfitnesspal-mcp" <<EOF
#!/usr/bin/env sh
exec "$ROOT/venv/bin/python" -m myfitnesspal_mcp.cli "\$@"
EOF
chmod +x "$ROOT/myfitnesspal-mcp"
echo "Installed MyFitnessPal MCP $VERSION at $ROOT"
echo "Verify: $ROOT/myfitnesspal-mcp verify --browser firefox"
echo "Server command: $ROOT/myfitnesspal-mcp serve"
echo "Use that absolute command as your MCP stdio executable, with no extra server-wide setup required."
