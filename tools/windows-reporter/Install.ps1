$ErrorActionPreference = 'Stop'
$destination = Join-Path $env:LOCALAPPDATA 'JiayangReport'
New-Item -ItemType Directory -Force $destination | Out-Null
Get-ChildItem -LiteralPath $PSScriptRoot -File | ForEach-Object {
    $target = Join-Path $destination $_.Name
    if ($_.FullName -ne $target) { Copy-Item -LiteralPath $_.FullName -Destination $target -Force }
}
$python = $null
$candidates = @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'))
foreach ($candidate in $candidates) { if (Test-Path $candidate) { $python = $candidate; break } }
if (-not $python) {
    Write-Host 'Installing Python for the current Windows user...'
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'Please install Python 3.13 from python.org (current user), then run Install.cmd again.' }
    & winget.exe install --id Python.Python.3.13 --exact --scope user --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
    $python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
}
if (-not (Test-Path $python)) { throw 'Python executable not found.' }
$venv = Join-Path $destination '.venv\Scripts\python.exe'
if (-not (Test-Path $venv)) { & $python -m venv (Join-Path $destination '.venv'); if ($LASTEXITCODE -ne 0) { throw 'venv failed' } }
& $venv -m pip install -r (Join-Path $destination 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; check network and retry.' }
& $venv -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed; check network and retry.' }
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jiayang Report.lnk'))
$shortcut.TargetPath = Join-Path $destination '.venv\Scripts\pythonw.exe'
$shortcut.Arguments = '"' + (Join-Path $destination 'reporter.py') + '"'
$shortcut.WorkingDirectory = $destination
$shortcut.Save()
Start-Process (Join-Path $destination '.venv\Scripts\pythonw.exe') -ArgumentList ('"' + (Join-Path $destination 'reporter.py') + '"') -WorkingDirectory $destination
Write-Host 'Installed. Use the Jiayang Report desktop shortcut to configure and test.'
