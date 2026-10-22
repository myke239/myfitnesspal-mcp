param([string]$Version = "latest")
$ErrorActionPreference = "Stop"
$repo = "myke239/myfitnesspal-mcp"
if ($Version -eq "latest") {
  $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
  $Version = $release.tag_name.TrimStart('v')
} else { $Version = $Version.TrimStart('v') }
$root = if ($env:MFP_INSTALL_DIR) { $env:MFP_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "MyFitnessPalMCP" }
$python = if ($env:PYTHON) { $env:PYTHON } else { "py" }
$pythonArgs = @()
if ($env:PYTHON) {
  & $python -c "import sys; raise SystemExit(sys.version_info < (3,11))" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "The Python executable in PYTHON must be version 3.11 or newer."
  }
} else {
  $launcherVersions = @(
    & py -0p 2>$null | ForEach-Object {
      if ($_ -match '(?<!\d)3\.(\d+)(?!\d)' -and [int]$Matches[1] -ge 11) {
        "3.$($Matches[1])"
      }
    } | Sort-Object { [version]$_ } -Descending -Unique
  )
  foreach ($launcherVersion in $launcherVersions) {
    & py "-$launcherVersion" -c "import sys; raise SystemExit(sys.version_info < (3,11))" *> $null
    if ($LASTEXITCODE -eq 0) {
      $pythonArgs = @("-$launcherVersion")
      break
    }
  }
  if (-not $pythonArgs) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
      $python = $pythonCommand.Source
      & $python -c "import sys; raise SystemExit(sys.version_info < (3,11))" *> $null
      if ($LASTEXITCODE -eq 0) { $pythonArgs = @() }
    }
  }
  if ($python -eq "py" -and -not $pythonArgs) {
    throw "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/windows/ and rerun this installer."
  }
  if ($python -ne "py" -and -not $pythonArgs -and $LASTEXITCODE -ne 0) {
    throw "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/windows/ and rerun this installer."
  }
}
$pythonVersion = & $python @pythonArgs -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) { throw "Could not run the selected Python interpreter." }
Write-Host "Using Python $pythonVersion"
New-Item -ItemType Directory -Force $root | Out-Null
$wheel = "myfitnesspal_mcp-$Version-py3-none-any.whl"
Invoke-WebRequest "https://github.com/$repo/releases/download/v$Version/$wheel" -OutFile (Join-Path $root $wheel)
$venv = Join-Path $root "venv"
& $python @pythonArgs -m venv $venv
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
