# Fetch pinned, unmodified browser dependencies from the official npm registry.
# Requires PowerShell 7 and tar. No npm install or package lifecycle scripts run.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'web/vendor-manifest.json') -Raw | ConvertFrom-Json
$outputDir = Join-Path $projectRoot 'web/vendor'
$cacheDir = Join-Path $projectRoot 'build/browser-deps'
New-Item -ItemType Directory -Force -Path $outputDir, $cacheDir | Out-Null

foreach ($package in $manifest.packages) {
    $packageName = $package.name.Replace('@', '').Replace('/', '-') + '-' + $package.version
    $archivePath = Join-Path $cacheDir ($packageName + '.tgz')
    if (!(Test-Path -LiteralPath $archivePath)) {
        Invoke-WebRequest -Uri $package.url -OutFile $archivePath -TimeoutSec 180
    }
    $sha = [System.Security.Cryptography.SHA512]::Create()
    $stream = [IO.File]::OpenRead($archivePath)
    try { $integrity = 'sha512-' + [Convert]::ToBase64String($sha.ComputeHash($stream)) }
    finally { $stream.Dispose(); $sha.Dispose() }
    if ($integrity -cne $package.integrity) {
        throw "Integrity mismatch for $packageName. Remove the cached archive and retry."
    }
    $extractDir = Join-Path $cacheDir $packageName
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    foreach ($file in $package.files.PSObject.Properties) {
        & tar -xzf $archivePath -C $extractDir $file.Name
        if ($LASTEXITCODE -ne 0) { throw "Cannot extract $($file.Name)." }
        Copy-Item -LiteralPath (Join-Path $extractDir $file.Name) -Destination (Join-Path $outputDir $file.Value) -Force
    }
    Write-Host "Installed $($package.name) $($package.version) ($($package.license))"
}
foreach ($license in $manifest.licenses.PSObject.Properties) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $license.Name) -Destination (Join-Path $outputDir $license.Value) -Force
}
Write-Host 'Browser processing dependencies are ready in web/vendor.'
