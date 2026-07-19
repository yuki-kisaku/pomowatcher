#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$RepoDir = $PSScriptRoot
$VenvDir = Join-Path $RepoDir ".venv-windows"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
$AppScript = Join-Path $RepoDir "pomowatcher_windows.py"
$Requirements = Join-Path $RepoDir "requirements-windows.txt"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Pomowatcher.lnk"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Get-CompatiblePython {
    $candidates = @(
        @{ Command = "py"; Arguments = @("-3.13") },
        @{ Command = "py"; Arguments = @("-3.12") },
        @{ Command = "py"; Arguments = @("-3.11") },
        @{ Command = "py"; Arguments = @("-3.10") },
        @{ Command = "python"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        $resolved = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $resolved) {
            continue
        }

        $checkArgs = @($candidate.Arguments) + @(
            "-c",
            "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)"
        )
        & $resolved.Source $checkArgs 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{
                Executable = $resolved.Source
                Arguments = @($candidate.Arguments)
            }
        }
    }
    return $null
}

function Get-Winget {
    $command = Get-Command "winget" -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "wingetが見つかりません。Microsoft Storeで『アプリ インストーラー』を更新してから再実行してください。"
    }
    return $command.Source
}

function Get-MpvExecutable {
    $command = Get-Command "mpv" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $appPath = Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe" `
        -Name "(default)" `
        -ErrorAction SilentlyContinue
    if ($appPath -and (Test-Path -LiteralPath $appPath -PathType Leaf)) {
        return $appPath
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "mpv\mpv.exe"),
        (Join-Path $env:ProgramFiles "MPV Player\mpv.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\mpv\mpv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Install-WingetPackage([string]$Id, [string]$Name) {
    $winget = Get-Winget
    Write-Step "$Name をインストール"
    & $winget install --id $Id --exact --source winget --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "$Name のインストールに失敗しました（終了コード: $LASTEXITCODE）"
    }
    Refresh-Path
}

if ($env:OS -ne "Windows_NT") {
    throw "install.ps1はWindows 11専用です。"
}
$build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
if ($build -lt 22000) {
    throw "このインストーラーはWindows 11専用です（検出したビルド: $build）。"
}

if (-not (Test-Path -LiteralPath $AppScript)) {
    throw "pomowatcher_windows.pyが見つかりません: $AppScript"
}
if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "requirements-windows.txtが見つかりません: $Requirements"
}

Write-Step "Python 3.10以上を確認"
$python = Get-CompatiblePython
if (-not $python) {
    Install-WingetPackage -Id "Python.Python.3.13" -Name "Python 3.13"
    $python = Get-CompatiblePython
}
if (-not $python) {
    throw "Pythonのインストール後も実行ファイルを確認できませんでした。Windowsへサインインし直して再実行してください。"
}

Write-Step "mpvを確認"
if (-not (Get-MpvExecutable)) {
    Install-WingetPackage -Id "shinchiro.mpv" -Name "mpv"
}
$mpv = Get-MpvExecutable
if (-not $mpv) {
    throw "mpvのインストール後も実行ファイルを確認できませんでした。"
}
Write-Host "mpv: $mpv"

Write-Step "Pomowatcher専用のPython環境を作成"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $venvArgs = @($python.Arguments) + @("-m", "venv", "--clear", $VenvDir)
    & $python.Executable $venvArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python環境の作成に失敗しました。"
    }
}

Write-Step "必要なPythonパッケージをインストール"
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pipの更新に失敗しました。"
}
& $VenvPython -m pip install --disable-pip-version-check -r $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Pythonパッケージのインストールに失敗しました。"
}
& $VenvPython -c "import PIL, pystray, windows_toasts, winrt.windows.media.control"
if ($LASTEXITCODE -ne 0) {
    throw "Pythonパッケージの読み込み確認に失敗しました。"
}

Write-Step "Windowsログイン時の自動起動を登録"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $VenvPythonw
$shortcut.Arguments = '"' + $AppScript + '"'
$shortcut.WorkingDirectory = $RepoDir
$shortcut.Description = "Pomowatcher for Windows 11"
$shortcut.Save()

if (-not $NoLaunch) {
    Write-Step "Pomowatcherを起動"
    Start-Process -FilePath $VenvPythonw -ArgumentList ('"{0}"' -f $AppScript) -WorkingDirectory $RepoDir -WindowStyle Hidden
}

Write-Host ""
Write-Host "インストールが完了しました。" -ForegroundColor Green
Write-Host "タイマーは通知領域で動作し、次回のWindowsログイン時にも自動で起動します。"
