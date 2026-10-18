param([switch]$Installer)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $projectPython)) { throw 'Create .venv and install requirements.txt plus pyinstaller first. See README.' }
& $projectPython -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build cancelled.' }
& $projectPython -m PyInstaller --noconfirm --clean --onedir --windowed --name GitPushAgent --collect-all vosk --collect-all sounddevice --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes main.py
if ($LASTEXITCODE -ne 0) { throw 'Application build failed. Close GitPush before rebuilding.' }
if ($Installer) {
    $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $innoCompiler = if ($compiler) { $compiler.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
    if (-not (Test-Path $innoCompiler)) { throw 'Install Inno Setup 6 or put ISCC.exe on PATH to build the optional installer.' }
    & $innoCompiler 'packaging\GitPushAgent.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    Write-Host 'Installer ready: dist\installer\GitPushAgent-Setup.exe'
} else {
    Write-Host 'App ready: dist\GitPushAgent\GitPushAgent.exe'
}
