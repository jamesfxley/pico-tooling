# SPDX-License-Identifier: MIT
# Install the AR-15 proxy and launcher into the current user's private config.
# Setup stops an old copy and removes its old logon shortcut, but starts no proxy.
# Only adding/removing the local-IPv4-subnet firewall rule requests elevation, once
# per change. -NoFirewall skips that step for CI/machines without the distro.
# -Remove preserves configuration/devices.toml and removes the installed copies,
# connection files and firewall rule. No software or board serial is installed.
# Exit status: 0 done; 2 pre-flight/firewall failed.

param(
    [string[]] $Workspace = @(),
    [int] $Port = 0,
    [switch] $Remove,
    [switch] $NoFirewall,
    [string] $ConfigDirectory = (Join-Path $env:APPDATA "pico"),
    [string] $StartupDirectory = [Environment]::GetFolderPath("Startup")
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$ConnectionFile = ".pico-device-proxy.json"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$ConfigPath = Join-Path $ConfigDirectory "device-proxy.json"
$Installed = Join-Path $ConfigDirectory "device-proxy.ps1"
$Shortcut = Join-Path $StartupDirectory "pico-device-proxy.lnk"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Launcher = Join-Path $ConfigDirectory "start-device-proxy.ps1"
$RuleName = "pico-device-proxy-wsl"
$DefaultPort = 47600

function Stop-Run([string] $Message) {
    Write-Output "STOP: $Message"
    exit 2
}

function Stop-Proxy {
    $found = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf('-File "' + $Installed + '"', [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.ProcessId -ne $PID })
    foreach ($process in $found) { Stop-Process -Id $process.ProcessId -Force }
    return $found.Count
}

function Read-Config {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { return $null }
    return Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
}

# Pre-flight.
# Inspect before any write, ACL change, shortcut change or process stop.
if (Test-Path -LiteralPath $ConfigDirectory) {
    if (-not (Test-Path -LiteralPath $ConfigDirectory -PathType Container)) {
        Stop-Run "$ConfigDirectory is not a configuration folder; nothing changed"
    }
    $ownedNames = @("device-proxy.ps1", "start-device-proxy.ps1", "device-proxy.json", "device-proxy.log", "devices.toml")
    $unexpected = @(Get-ChildItem -LiteralPath $ConfigDirectory -Force |
        Where-Object { $_.PSIsContainer -or $_.Name -notin $ownedNames } |
        Select-Object -ExpandProperty Name)
    if ($unexpected.Count -gt 0) {
        Stop-Run ("unexpected entries in ${ConfigDirectory}: " + ($unexpected -join ", ") + "; nothing changed")
    }
}

if (-not $env:APPDATA -or -not $env:SystemRoot) { Stop-Run "APPDATA or SystemRoot is not set" }
if ($PSVersionTable.PSVersion -lt [version] "5.1") { Stop-Run "Windows PowerShell 5.1 is needed" }
if (-not (Test-Path -LiteralPath $PowerShell -PathType Leaf)) { Stop-Run "$PowerShell not found" }
if (-not $Remove) {
    $source = Join-Path $Here "device-proxy.ps1"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Stop-Run "$source not found" }
    $launcherSource = Join-Path $Here "start-device-proxy.ps1"
    if (-not (Test-Path -LiteralPath $launcherSource -PathType Leaf)) { Stop-Run "$launcherSource not found" }
    foreach ($folder in $Workspace) {
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) { Stop-Run "workspace $folder does not exist" }
    }
}

function Test-ProxyFirewall($Rule, [int] $ProxyPort) {
    if ($null -eq $Rule) { return $false }
    $ports = $Rule | Get-NetFirewallPortFilter
    $addresses = $Rule | Get-NetFirewallAddressFilter
    $interfaces = $Rule | Get-NetFirewallInterfaceFilter
    $types = $Rule | Get-NetFirewallInterfaceTypeFilter
    # Accept documented literal filter values only; native read-back is a host check.
    return ($Rule.Enabled -eq "True" -and $Rule.Direction -eq "Inbound" -and
        $Rule.Action -eq "Allow" -and [string] $Rule.Profile -eq "Any" -and
        [string] $ports.Protocol -in @("TCP", "6") -and [string] $ports.LocalPort -eq [string] $ProxyPort -and
        [string] $ports.RemotePort -eq "Any" -and [string] $addresses.LocalAddress -eq "Any" -and
        @($addresses.RemoteAddress).Count -eq 1 -and [string] $addresses.RemoteAddress -eq "LocalSubnet4" -and
        @($interfaces.InterfaceAlias).Count -eq 1 -and [string] $interfaces.InterfaceAlias -eq "Any" -and
        [string] $types.InterfaceType -eq "Any")
}

# One elevated child owns only the named firewall operation. No workspace or
# user-supplied command text is evaluated with elevation.
function Set-ProxyFirewall([switch] $Delete) {
    if ($NoFirewall) { Write-Output "firewall: skipped (-NoFirewall)"; return }
    $rule = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
    if ($Delete -and $null -eq $rule) { return }
    if (-not $Delete -and (Test-ProxyFirewall $rule $Port)) {
        Write-Output "firewall: kept $RuleName (inbound TCP $Port, LocalSubnet4, all profiles/interfaces)"
        return
    }
    if (-not $Delete -and $null -ne $rule) {
        Write-Output "firewall: replacing $RuleName with inbound TCP $Port from LocalSubnet4 on all profiles/interfaces"
    }
    $operation = if ($Delete) {
        "Remove-NetFirewallRule -Name '$RuleName'"
    } else {
        "Get-NetFirewallRule -Name '$RuleName' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; New-NetFirewallRule -Name '$RuleName' -DisplayName '$RuleName' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet4 -Profile Any | Out-Null"
    }
    $code = "`$ErrorActionPreference='Stop'; try { $operation; exit 0 } catch { [Console]::Error.WriteLine(`$_.Exception.Message); exit 2 }"
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($code))
    try {
        $child = Start-Process -FilePath $PowerShell -ArgumentList "-NoProfile -EncodedCommand $encoded" -Verb RunAs -Wait -PassThru
    } catch { Stop-Run "firewall elevation was cancelled or failed: $($_.Exception.Message)" }
    if ($child.ExitCode -ne 0) { Stop-Run "firewall operation failed: $($child.ExitCode)" }
    Write-Output "firewall: updated $RuleName"
}

if ($Remove) {
    Set-ProxyFirewall -Delete
    $stopped = Stop-Proxy
    $config = Read-Config
    if ($null -ne $config) {
        foreach ($folder in @($config.workspaces)) {
            Remove-Item -LiteralPath (Join-Path ([string] $folder) $ConnectionFile) -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut; Write-Output "removed previous logon shortcut: $Shortcut" }
    foreach ($path in $Installed, $Launcher) { Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue }
    Write-Output "removed: stopped $stopped process(es); installed copies and connection files are gone"
    Write-Output "kept: $ConfigPath and devices.toml in $ConfigDirectory"
    exit 0
}

# The configuration: what was set before, plus what this run names.
$existing = Read-Config
$folders = @()
if ($null -ne $existing) { $folders += @($existing.workspaces) }
$folders += $Workspace
$folders = @($folders | ForEach-Object { [System.IO.Path]::GetFullPath([string] $_) } | Select-Object -Unique)
if ($folders.Count -eq 0) { Stop-Run "name the folder that holds your repositories: -Workspace <folder>" }
if ($Port -eq 0) { if ($null -ne $existing) { $Port = [int] $existing.port } else { $Port = $DefaultPort } }

if ($Port -lt 1 -or $Port -gt 65535) { Stop-Run "port must be between 1 and 65535" }
Set-ProxyFirewall
New-Item -ItemType Directory -Force -Path $ConfigDirectory | Out-Null
# This directory is host-only; workspace processes must not control the script
# that enforces the allow-list. Remove inherited access for other users.
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = (Get-Item -LiteralPath $ConfigDirectory).GetAccessControl(
    [System.Security.AccessControl.AccessControlSections]::Access)
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $identity, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
$matchesRule = $acl.AreAccessRulesProtected -and $rules.Count -eq 1
if ($matchesRule) {
    $matchesRule = $rules[0].IdentityReference -eq $identity -and
        $rules[0].FileSystemRights -eq $rule.FileSystemRights -and
        $rules[0].InheritanceFlags -eq $rule.InheritanceFlags -and
        $rules[0].PropagationFlags -eq $rule.PropagationFlags -and
        $rules[0].AccessControlType -eq $rule.AccessControlType
}
if (-not $matchesRule) {
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($existingRule in @($acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]))) {
        $acl.RemoveAccessRuleSpecific($existingRule)
    }
    $acl.AddAccessRule($rule)
    (Get-Item -LiteralPath $ConfigDirectory).SetAccessControl($acl)
}
$json = [ordered]@{ port = $Port; workspaces = $folders } | ConvertTo-Json
[System.IO.File]::WriteAllText($ConfigPath, $json, $Utf8)
[void] (Stop-Proxy)
foreach ($folder in $folders) { Remove-Item -LiteralPath (Join-Path $folder $ConnectionFile) -ErrorAction SilentlyContinue }
if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut; Write-Output "removed previous logon shortcut: $Shortcut" }
Copy-Item -LiteralPath $source -Destination $Installed -Force
Copy-Item -LiteralPath $launcherSource -Destination $Launcher -Force
Write-Output "config: $ConfigPath"
Write-Output "allow-list (yours to write): $(Join-Path $ConfigDirectory 'devices.toml')"
Write-Output "installed launcher: $Launcher"
Write-Output "ok: run the launcher before opening the dev container"
exit 0
