param([string]$FFmpegPath = '', [string]$OutputDirectory = 'release/current', [string]$PythonPath = '.venv/Scripts/python.exe')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = if ([IO.Path]::IsPathRooted($PythonPath)) { $PythonPath } else { Join-Path $PSScriptRoot $PythonPath }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv and install requirements-desktop.txt first.' }
if (-not $FFmpegPath) {
    $candidate = 'C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin/ffmpeg.exe'
    if (Test-Path -LiteralPath $candidate) { $FFmpegPath = $candidate }
    else { $FFmpegPath = (Get-Command ffmpeg.exe -ErrorAction Stop).Source }
}
if ((Get-Item -LiteralPath $FFmpegPath).Length -lt 1000000) { throw 'Pass the actual FFmpeg binary, not a command shim: -FFmpegPath <path>' }
New-Item -ItemType Directory -Path 'vendor',$OutputDirectory,'licenses' -Force | Out-Null
Copy-Item -LiteralPath $FFmpegPath -Destination 'vendor/ffmpeg.exe' -Force
$ffmpegRoot = Split-Path (Split-Path $FFmpegPath -Parent) -Parent
if (Test-Path -LiteralPath (Join-Path $ffmpegRoot 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $ffmpegRoot 'LICENSE') -Destination 'licenses/FFmpeg-LICENSE.txt' -Force
}
if (Test-Path -LiteralPath (Join-Path $ffmpegRoot 'README.txt')) {
    Copy-Item -LiteralPath (Join-Path $ffmpegRoot 'README.txt') -Destination 'licenses/FFmpeg-README.txt' -Force
}
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build/pyinstaller-cache'
& $pythonPath -m PyInstaller --noconfirm --onefile --windowed --noupx --name Dongdong --icon "$PSScriptRoot/web/brand.ico" --version-file "$PSScriptRoot/deploy/windows-version.txt" --distpath $OutputDirectory --workpath build/pyinstaller --specpath build --add-data "$PSScriptRoot/web;web" --add-data "$PSScriptRoot/licenses;licenses" --add-data "$PSScriptRoot/THIRD_PARTY.md;." --add-data "$PSScriptRoot/THIRD-PARTY-NOTICES.md;." --add-data "$PSScriptRoot/LICENSE;." --add-data "$PSScriptRoot/updates.json;." --add-binary "$PSScriptRoot/vendor/ffmpeg.exe;vendor" --collect-all yt_dlp --collect-all webview --copy-metadata requests --copy-metadata Flask --copy-metadata waitress --copy-metadata pywebview --copy-metadata certifi app.py
if ($LASTEXITCODE -ne 0) { throw 'EXE packaging failed.' }
Copy-Item -LiteralPath 'start-web.bat','README.md','THIRD_PARTY.md','THIRD-PARTY-NOTICES.md','LICENSE','updates.json' -Destination $OutputDirectory -Force
Copy-Item -LiteralPath 'licenses' -Destination $OutputDirectory -Recurse -Force
Write-Output "Built $OutputDirectory/Dongdong.exe (Windows x64)."
