param(
    [Parameter(Position=0)]
    [ValidateSet('verify','tunnel-setup','tunnel','tunnel-status','remote-reset','gateway')]
    [string]$Command = 'verify',
    [string]$Domain,
    [string]$GarminPython,
    [string]$GarminData
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Install the project virtual environment first.' }
$env:MFP_BROWSER = 'firefox'
switch ($Command) {
    'gateway' {
        if (-not $GarminPython -or -not $GarminData) { throw 'Provide -GarminPython and -GarminData.' }
        & $Python -m myfitnesspal_mcp.gateway --garmin-python $GarminPython --garmin-data $GarminData
    }
    'verify' { & $Python -m myfitnesspal_mcp.cli verify --browser firefox }
    'tunnel-setup' {
        if ($GarminData) { & $Python -m myfitnesspal_mcp.tunnel setup --reuse-garmin-data $GarminData }
        else { & $Python -m myfitnesspal_mcp.tunnel setup }
    }
    'tunnel' { & $Python -m myfitnesspal_mcp.tunnel run --domain $Domain }
    'tunnel-status' { & $Python -m myfitnesspal_mcp.tunnel status }
    'remote-reset' { & $Python -m myfitnesspal_mcp.remote reset }
}
exit $LASTEXITCODE
