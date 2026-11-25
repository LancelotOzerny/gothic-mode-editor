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

# Use Tkinter's native initializer: Tcl's "package require Tk" can search for
# tk86t.dll under bin/ even when Python ships the DLL under DLLs/.
# Catch the probe error in Python so PowerShell 5.1's Stop preference does not
# turn redirected native stderr into a terminating error before our fallback.
$tkProbe = @'
import sys
try:
    import tkinter
    root = tkinter.Tk()
    root.withdraw()
    root.update_idletasks()
    root.destroy()
except Exception as exc:
    print(f'{type(exc).__name__}: {exc}')
    sys.exit(1)
'@

try {
    if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
        throw "Entry point not found: $entryPoint"
    }
    if (-not (Test-Path -LiteralPath $assetsPath -PathType Container)) {
        throw "Assets directory not found: $assetsPath"
    }
    # Windows cannot replace an executable that is still running. Detect this
    # before spending time on packaging, without terminating the user's editor.
    if (Test-Path -LiteralPath $exePath -PathType Leaf) {
        try {
            $outputHandle = [System.IO.File]::Open($exePath, [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            $outputHandle.Dispose()
        }
        catch {
            throw "Cannot replace '$exePath'. Save your work and close all GothicEditor windows, then run compile.ps1 again. If the editor is closed, check file permissions or another process locking the EXE. Details: $($_.Exception.Message)"
        }
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
    # PyInstaller's frozen executable can leave Tcl/Tk environment variables
    # pointing to a temporary _MEI... directory. Those paths break a normal
    # Python interpreter in the same terminal, even when Tcl/Tk is installed.
    foreach ($variable in @('TCL_LIBRARY', 'TK_LIBRARY')) {
        $value = [Environment]::GetEnvironmentVariable($variable, 'Process')
        if ($value -and ($value -match '(?i)[\\/]_MEI[0-9A-Za-z]+[\\/]' -or
                         -not (Test-Path -LiteralPath $value -PathType Container))) {
            Write-Host "Ignoring stale ${variable}: $value"
            [Environment]::SetEnvironmentVariable($variable, $null, 'Process')
        }
    }

    # Initialize both Tcl and Tk, withdrawing and disposing the test window.
    $tkDiagnostic = & $Python -c $tkProbe
    if ($LASTEXITCODE -ne 0) {
        # Explicitly locate the standard Windows python.org Tcl directory.
        # Some Python setups do not find it when run from another environment.
        $pythonRoot = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
        $tclRoot = Join-Path $pythonRoot 'tcl'
        $tclCandidates = @(Get-ChildItem -LiteralPath $tclRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^tcl8\.' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'init.tcl')) } |
            Sort-Object Name -Descending)
        $tkCandidates = @(Get-ChildItem -LiteralPath $tclRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^tk8\.' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'tk.tcl')) } |
            Sort-Object Name -Descending)
        if ($tclCandidates.Count -gt 0 -and $tkCandidates.Count -gt 0) {
            $env:TCL_LIBRARY = $tclCandidates[0].FullName
            $env:TK_LIBRARY = $tkCandidates[0].FullName
            Write-Host "Tcl: $env:TCL_LIBRARY"
            Write-Host "Tk:  $env:TK_LIBRARY"
        }
        else {
            throw "Tkinter cannot find Tcl/Tk for '$Python'. Check '$tclRoot' for tcl8.x/init.tcl and tk8.x/tk.tcl. If missing, repair Python with the Tcl/Tk and IDLE component enabled. Probe: $($tkDiagnostic -join [Environment]::NewLine)"
        }
        $tkDiagnostic = & $Python -c $tkProbe
        if ($LASTEXITCODE -ne 0) {
            throw "Tcl/Tk is still unavailable for '$Python'. Repair the Python installation, or run .\compile.ps1 -Python <path-to-working-python.exe>. Probe: $($tkDiagnostic -join [Environment]::NewLine)"
        }
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
