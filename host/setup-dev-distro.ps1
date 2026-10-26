# SPDX-License-Identifier: MIT
# AR-15: Windows PowerShell 5.1; run unelevated with WSL already installed.
param(
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_-]*$')]
    [string] $Distro = "pico-dev",
    [string] $User = ($env:USERNAME.ToLower() -replace '[^a-z0-9_-]', ''),
    [string] $Image
)
$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"
# Canonical: releases.ubuntu.com/26.04.1/SHA256SUMS; Docker apt version from
# docs.docker.com/engine/install/ubuntu (the matching package suffix is queried).
$ImageUrl = "https://releases.ubuntu.com/26.04.1/ubuntu-26.04.1-wsl-amd64.wsl"
$ImageSha256 = "48d56724b5c8e60f24893e83e73bbb58c60b3ca22fba3da977075420acd54104"
$DockerVersion = "29.8.2"
$temp = $null
function Invoke-Wsl([string[]] $Arguments) {
    # Do not redirect native stderr under Stop in Windows PowerShell 5.1.
    & wsl.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "wsl.exe failed with exit code $LASTEXITCODE" }
}
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run unelevated; WSL must already be installed" }
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -cne "AMD64") { throw "The pinned image requires an amd64 host" }
    if ($User -cnotmatch '^[a-z_][a-z0-9_-]{0,31}$' -or $User -ceq "root") { throw "Supply -User with a non-root Linux user name (1-32 lowercase letters, digits, _ or -, starting with a letter or _)" }
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "wsl.exe is missing; install and enable WSL 2.4.10 or newer first" }
    # Component versions do not require a registered distro. Microsoft does not
    # specify the empty-list exit code; do not use that code as an install check.
    & wsl.exe --version
    if ($LASTEXITCODE -ne 0) { throw "WSL is not installed or its version query is unavailable; install and enable WSL 2.4.10 or newer first" }
    $distros = @(& wsl.exe --list --quiet)
    if ($LASTEXITCODE -ne 0) { $distros = @() }
    $distros = @($distros | ForEach-Object { "$_".Replace("`0", "").Trim() })
    if ($distros -contains $Distro) { throw "A distro named $Distro already exists; nothing changed" }
    $wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
    if (Test-Path -LiteralPath $wslconfig) {
        foreach ($line in (Get-Content -LiteralPath $wslconfig)) {
            if ($line -match '^\s*networkingMode\s*=\s*([^#;]*?)\s*(?:[#;].*)?$' -and $Matches[1].Trim() -ine "nat") { throw "$wslconfig sets a networkingMode other than NAT" }
        }
    }
    $destination = Join-Path $env:LOCALAPPDATA $Distro
    if (Test-Path -LiteralPath $destination) { throw "Install directory already exists: $destination" }
    $shell = Join-Path $PSScriptRoot "in-dev-distro.sh"
    if (-not (Test-Path -LiteralPath $shell -PathType Leaf)) { throw "Not found: $shell" }
    $temp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $temp | Out-Null
    $archive = Join-Path $temp "ubuntu-26.04.1-wsl-amd64.wsl"
    if ($Image) {
        Copy-Item -LiteralPath $Image -Destination $archive
    } else {
        # Windows PowerShell 5.1's progress display slows large downloads.
        $savedProgress = $ProgressPreference
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri $ImageUrl -OutFile $archive
        } finally { $ProgressPreference = $savedProgress }
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() -cne $ImageSha256) { throw "Image SHA-256 mismatch; temporary copy will be removed; no distro imported" }
    # Canonical's .wsl method; Microsoft's basic-commands and build-custom-distro
    # document location, no-launch and name. Skip automatic launch; provision as root.
    Invoke-Wsl @('--install', '--from-file', $archive, '--name', $Distro, '--location', $destination, '--no-launch')
    Invoke-Wsl @('--cd', '/', '-d', $Distro, '-u', 'root', '--exec', 'mkdir', '-p', '/opt/pico-setup')
    $installed = "\\wsl.localhost\$Distro\opt\pico-setup\in-dev-distro.sh"
    # Write LF/no BOM even when the Windows checkout converted line endings.
    $content = [IO.File]::ReadAllText($shell).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($installed, $content, (New-Object Text.UTF8Encoding($false)))
    Invoke-Wsl @('--cd', '/', '-d', $Distro, '-u', 'root', '--exec', 'sh', '/opt/pico-setup/in-dev-distro.sh', 'setup', $User, $DockerVersion)
    Invoke-Wsl @('--terminate', $Distro)
    $active = $false
    foreach ($attempt in 1..45) {
        $state = & wsl.exe --cd / -d $Distro -u root --exec systemctl is-active docker
        if ($LASTEXITCODE -eq 0 -and "$state".Trim() -ceq "active") { $active = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $active) { throw "The docker service did not become active within 45 checks" }
    Invoke-Wsl @('--cd', '/', '-d', $Distro, '-u', 'root', '--exec', 'sh', '/opt/pico-setup/in-dev-distro.sh', 'verify')
    Write-Output "Distro $Distro is ready. Put your workspace at \\wsl.localhost\$Distro\home\$User\<folder>."
    $proxySetup = (Join-Path $PSScriptRoot "setup-device-proxy.ps1").Replace("'", "''")
    Write-Output "Next: & '$proxySetup' -Workspace '\\wsl.localhost\$Distro\home\$User\<folder>'"
    Write-Output "Use an ordinary Windows VS Code window: dev.containers.executeInWSL=true, dev.containers.executeInWSLDistro=$Distro. See guides/device.md for setup and the launcher."
} catch {
    Write-Host "STOP: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Any registered distro is retained; setup never unregisters or replaces it."
    exit 2
} finally {
    if ($temp -and (Test-Path -LiteralPath $temp)) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
