param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path
)

$ErrorActionPreference = 'Stop'
$certificate = $env:WINDOWS_SIGNING_PFX_BASE64
$password = $env:WINDOWS_SIGNING_PFX_PASSWORD

if ([string]::IsNullOrWhiteSpace($certificate) -and [string]::IsNullOrWhiteSpace($password)) {
    Write-Host 'No Authenticode certificate configured; Windows binaries will be unsigned.'
    exit 0
}
if ([string]::IsNullOrWhiteSpace($certificate) -or [string]::IsNullOrWhiteSpace($password)) {
    throw 'Configure both WINDOWS_SIGNING_PFX_BASE64 and WINDOWS_SIGNING_PFX_PASSWORD secrets.'
}

$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
$signtool = Get-ChildItem -LiteralPath $sdkRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $signtool) {
    throw 'Windows SDK SignTool was not found on the GitHub Actions runner.'
}

$certificatePath = Join-Path $env:RUNNER_TEMP 'das-kreb-code-signing.pfx'
try {
    [IO.File]::WriteAllBytes($certificatePath, [Convert]::FromBase64String($certificate))
    foreach ($file in $Path) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Signing input does not exist: $file"
        }
        & $signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f $certificatePath /p $password $file
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed: $file" }
        & $signtool verify /pa /all $file
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signature verification failed: $file" }
    }
    Write-Host 'All Windows executables are Authenticode-signed and verified.'
}
finally {
    Remove-Item -LiteralPath $certificatePath -Force -ErrorAction SilentlyContinue
}
