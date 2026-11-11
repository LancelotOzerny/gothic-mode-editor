# Build Gothic Editor from any working directory. No packages are installed here.
[CmdletBinding()]
param(
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$entryPoint = Join-Path $projectRoot 'main.py'
$assetsPath = Join-Path $projectRoot 'assets'
$distPath = Join-Path $projectRoot 'dist'
$buildPath = Join-Path $projectRoot 'build\pyinstaller'
$iconPath = Join-Path $projectRoot 'icon.ico'
$exePath = Join-Path $distPath 'GothicEditor.exe'

try {
    if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
        throw "Entry point not found: $entryPoint"
    }
    if (-not (Test-Path -LiteralPath $assetsPath -PathType Container)) {
        throw "Assets directory not found: $assetsPath"
    }

    if (-not $Python) {
        # Respect an activated environment; otherwise prefer a local environment.
        $candidates = @()
        if ($env:VIRTUAL_ENV) {
            $candidates += Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        }
        $candidates += Join-Path $projectRoot '.venv\Scripts\python.exe'
        $candidates += Join-Path $projectRoot 'venv\Scripts\python.exe'
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $Python = $candidate
                break
            }
        }
        if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
    }
    # Resolve a supplied interpreter before changing the working directory.
    $Python = (Get-Command $Python -ErrorAction Stop).Source
    & $Python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('PyInstaller') else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed for '$Python'. Install it in that environment before building."
    }
    & $Python -c "import tkinter; tkinter.Tcl().eval('info library')"
    if ($LASTEXITCODE -ne 0) {
        throw "Tcl/Tk is unavailable for '$Python'. Build from an environment with a working Tkinter installation."
    }

    $buildArguments = @(
        '-m', 'PyInstaller',
        '--onefile', '--windowed', '--noconfirm', '--clean',
        '--name', 'GothicEditor',
        '--distpath', $distPath,
        '--workpath', $buildPath,
        '--specpath', $buildPath,
        '--add-data', "${assetsPath}:assets"
    )
    if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
        $buildArguments += @('--icon', $iconPath)
        Write-Host "Icon: $iconPath"
    }
    $buildArguments += $entryPoint

    Write-Host "Python: $Python"
    Push-Location -LiteralPath $projectRoot
    try {
        & $Python @buildArguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "The build did not produce $exePath"
    }
    Write-Host "Build complete: $exePath"
}
catch {
    [Console]::Error.WriteLine("Build failed: " + $_.Exception.Message)
    exit 1
}
