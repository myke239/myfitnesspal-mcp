param([string]$Version = "latest")
$ErrorActionPreference = "Stop"
$repo = "myke239/myfitnesspal-mcp"
if ($Version -eq "latest") {
  $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
  $Version = $release.tag_name.TrimStart('v')
} else { $Version = $Version.TrimStart('v') }
$root = if ($env:MFP_INSTALL_DIR) { $env:MFP_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "MyFitnessPalMCP" }
$python = if ($env:PYTHON) { $env:PYTHON } else { "py" }
if ($python -eq "py") { & py -3 -c "import sys; assert sys.version_info >= (3,11)" }
else { & $python -c "import sys; assert sys.version_info >= (3,11)" }
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }
New-Item -ItemType Directory -Force $root | Out-Null
$wheel = "myfitnesspal_mcp-$Version-py3-none-any.whl"
Invoke-WebRequest "https://github.com/$repo/releases/download/v$Version/$wheel" -OutFile (Join-Path $root $wheel)
$venv = Join-Path $root "venv"
if ($python -eq "py") { & py -3 -m venv $venv } else { & $python -m venv $venv }
if ($LASTEXITCODE -ne 0) { throw "Could not create Python environment." }
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install (Join-Path $root $wheel)
if ($LASTEXITCODE -ne 0) { throw "Package installation failed." }
Write-Host "Installed MyFitnessPal MCP $Version at $root"
Write-Host "Verify: & '$venvPython' -m myfitnesspal_mcp.cli verify --browser firefox"
Write-Host "Server executable: $venvPython"
Write-Host "MCP arguments: -m myfitnesspal_mcp.cli serve"
Write-Host "Set MFP_BROWSER=firefox in the MCP server environment."
