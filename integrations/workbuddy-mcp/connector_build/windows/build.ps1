param(
  [Parameter(Mandatory = $true)][string]$Version,
  [ValidateSet("internal", "production")][string]$Channel = "internal",
  [string]$OutputDir = "release"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$release = [System.IO.Path]::GetFullPath((Join-Path $root $OutputDir))
$work = Join-Path $root "build"
$env:CONNECTOR_ARCH = "x64"
python (Join-Path $root "connector_build\build_binary.py") --output-dir (Join-Path $work "binary") --work-dir $work

$env:CONNECTOR_VERSION = $Version
$env:CONNECTOR_BINARY = Join-Path $work "binary\kap-workbuddy-connector.exe"
$env:CONNECTOR_OUTPUT = $release
New-Item -ItemType Directory -Force -Path $release | Out-Null
$isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
$iscc = if ($isccCommand) {
  $isccCommand.Source
} else {
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path -LiteralPath $iscc)) { throw "Inno Setup compiler was not found." }
& $iscc (Join-Path $root "connector_build\windows\connector.iss")

$filename = "kap-workbuddy-connector-$Version-windows-x64-setup.exe"
$artifact = Join-Path $release $filename
$signed = $false
if ($Channel -eq "production") {
  $required = @("WINDOWS_SIGNING_PFX_BASE64", "WINDOWS_SIGNING_PFX_PASSWORD")
  foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
      throw "Production Windows release requires signing credentials."
    }
  }
  $pfx = Join-Path $env:RUNNER_TEMP "kap-workbuddy-signing.pfx"
  [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_SIGNING_PFX_BASE64))
  try {
    $signtoolCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($signtoolCommand) {
      $signtool = $signtoolCommand.Source
    } else {
      $signtool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $signtool) { throw "Windows SDK signing tool was not found." }
    & $signtool sign /fd SHA256 /td SHA256 /tr "http://timestamp.digicert.com" /f $pfx /p $env:WINDOWS_SIGNING_PFX_PASSWORD $artifact
    & $signtool verify /pa $artifact
    $signed = $true
  } finally {
    Remove-Item -LiteralPath $pfx -Force -ErrorAction SilentlyContinue
  }
}

$metadata = @{
  platform = "windows"
  architecture = "x64"
  filename = $filename
  signed = $signed
  notarized = $false
} | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $release "$filename.metadata.json"), $metadata)
