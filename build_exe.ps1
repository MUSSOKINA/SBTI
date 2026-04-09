# Run from repo root: .\build_exe.ps1
# Output: dist\SBTI\SBTI.exe (distribute the whole dist\SBTI folder)
$ErrorActionPreference = "Stop"

if (-not $PSScriptRoot) {
    $PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $PSScriptRoot) {
    $PSScriptRoot = (Get-Location).Path
}
Set-Location -LiteralPath $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Missing $venvPy — check that `"python -m venv .venv`" succeeded."
}
# Single string path for call operator (must not be $null)
$pythonExe = (Resolve-Path -LiteralPath $venvPy).Path

$pipI = "https://pypi.org/simple"
function Invoke-Py {
    param([string[]]$PyArgs)
    $p = Start-Process -FilePath $pythonExe -ArgumentList $PyArgs -Wait -NoNewWindow -PassThru
    if ($p.ExitCode -ne 0) { throw "python $($PyArgs -join ' ') exited $($p.ExitCode)" }
}

Invoke-Py @("-m", "pip", "install", "-q", "-U", "pip", "-i", $pipI)
Invoke-Py @("-m", "pip", "install", "-q", "-r", "requirements.txt", "-i", $pipI)
Invoke-Py @("-m", "pip", "install", "-q", "pyinstaller", "-i", $pipI)

$addData = "image;image"
if (-not (Test-Path -LiteralPath "image")) {
    Write-Warning "Folder 'image' missing; creating empty folder. Add type images and rebuild."
    New-Item -ItemType Directory -Path "image" -Force | Out-Null
}

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--windowed",
    "--name", "SBTI",
    "--add-data", $addData,
    "--collect-all", "customtkinter",
    "sbti_gui.py"
)
Invoke-Py $pyiArgs

Write-Host "Done: dist\SBTI\SBTI.exe (zip and ship the entire dist\SBTI folder)"
