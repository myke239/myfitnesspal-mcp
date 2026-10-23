$ErrorActionPreference = 'Stop'
$tools = Join-Path $PSScriptRoot '..\work\tools\inno'
$tools = [System.IO.Path]::GetFullPath($tools)
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$installer = Join-Path $tools 'innosetup-6.7.3.exe'
$url = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe'
Invoke-WebRequest -Uri $url -OutFile $installer
$signature = Get-AuthenticodeSignature -FilePath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') {
    throw 'The Inno Setup installer signature could not be verified.'
}
$target = Join-Path $tools 'installed'
Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=$target") -Wait
$compiler = Join-Path $target 'ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Inno Setup compiler was not installed.' }
Write-Output $compiler
