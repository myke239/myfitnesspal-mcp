$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$bundle = Join-Path $repo 'dist\windows'
$python = 'python'
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $python = $venvPython }
Remove-Item -LiteralPath $bundle -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $bundle | Out-Null

$runtimeArgs = @(
    '--noconfirm', '--clean', '--onefile',
    '--icon', 'assets/branding/das-kreb-logo.ico',
    '--collect-all', 'myfitnesspal',
    '--collect-all', 'browser_cookie3',
    '--collect-submodules', 'mcp.server',
    '--collect-submodules', 'mcp.shared',
    '--collect-data', 'mcp',
    '--collect-all', 'truststore',
    '--collect-all', 'PIL',
    '--collect-all', 'tzdata',
    '--collect-all', 'ngrok',
    '--hidden-import', 'win32crypt'
)
$setupArgs = @(
    '--noconfirm', '--clean', '--onefile',
    '--icon', 'assets/branding/das-kreb-logo.ico',
    '--collect-all', 'PIL'
)

& $python -m PyInstaller @runtimeArgs --collect-all myfitnesspal_mcp --console --name myfitnesspal-mcp --distpath $bundle scripts/windows_mcp_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Could not build the MyFitnessPal MCP runtime.' }
& $python -m PyInstaller @setupArgs --windowed --name myfitnesspal-setup --distpath $bundle scripts/windows_setup_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Could not build the MyFitnessPal setup app.' }

$branding = Join-Path $bundle 'branding'
New-Item -ItemType Directory -Force -Path $branding | Out-Null
Copy-Item -LiteralPath 'assets/branding/das-kreb-logo.ico' -Destination (Join-Path $branding 'das-kreb-logo.ico') -Force
Copy-Item -LiteralPath 'assets/branding/das-kreb-logo.png' -Destination (Join-Path $branding 'das-kreb-logo.png') -Force
$pluginDest = Join-Path $bundle 'marketplace/plugins/myfitnesspal'
New-Item -ItemType Directory -Force -Path $pluginDest | Out-Null
Copy-Item -Path 'plugins/myfitnesspal/*' -Destination $pluginDest -Recurse -Force
$marketplaceDest = Join-Path $bundle 'marketplace/.agents/plugins'
New-Item -ItemType Directory -Force -Path $marketplaceDest | Out-Null
Copy-Item -LiteralPath 'scripts/marketplace/.agents/plugins/marketplace.json' -Destination $marketplaceDest -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination $bundle -Force
Copy-Item -LiteralPath 'LICENSE' -Destination $bundle -Force
Write-Output "Windows bundle ready: $bundle"
