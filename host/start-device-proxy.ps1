# SPDX-License-Identifier: MIT
# Start the installed AR-15 proxy before opening the dev container.
param(
    [string] $Distro = "pico-dev",
    [string] $ConfigDirectory = (Join-Path $env:APPDATA "pico")
)
$ErrorActionPreference = "Stop"
$RuleName = "pico-device-proxy-wsl"
$InterfaceAlias = "vEthernet (WSL (Hyper-V firewall))"
$Installed = Join-Path $ConfigDirectory "device-proxy.ps1"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
function Stop-Run([string] $Message) { Write-Output "STOP: $Message"; exit 2 }

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

if ([string]::IsNullOrWhiteSpace($Distro) -or $Distro.Contains('"')) { Stop-Run "name a WSL distro, normally pico-dev" }
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Stop-Run "wsl.exe is missing; set up pico-dev first" }
if (-not (Test-Path -LiteralPath $Installed -PathType Leaf)) { Stop-Run "run setup-device-proxy.ps1 first; $Installed is missing" }
try {
    $config = Get-Content -Raw -LiteralPath (Join-Path $ConfigDirectory "device-proxy.json") | ConvertFrom-Json
    $port = [int] $config.port
    if ($port -lt 1 -or $port -gt 65535 -or @($config.workspaces).Count -eq 0) { throw "invalid port/workspaces" }
} catch { Stop-Run "invalid proxy configuration: $($_.Exception.Message)" }
try {
    $route = @(& wsl.exe --cd / -d $Distro --exec ip route show default 2>&1)
    if ($LASTEXITCODE -ne 0) { throw ($route -join ' ') }
} catch { Stop-Run "cannot query WSL distro ${Distro}; ensure it exists: $($_.Exception.Message)" }
$gateways = @($route | ForEach-Object { if ([string] $_ -match '^default via ([0-9.]+) ') { $Matches[1] } } | Select-Object -Unique)
if ($gateways.Count -ne 1) { Stop-Run "$Distro needs one IPv4 default gateway in NAT mode" }
$gateway = $gateways[0]
$local = @(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $InterfaceAlias -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -ceq $gateway })
if ($local.Count -ne 1) { Stop-Run "$gateway is not Windows' address on $InterfaceAlias; use WSL NAT mode" }
try {
    $docker = @(& wsl.exe --cd / -d $Distro --exec docker ps -q 2>&1)
    if ($LASTEXITCODE -ne 0) { throw ($docker -join ' ') }
} catch { Stop-Run "Docker service in $Distro is unavailable: $($_.Exception.Message)" }
$rule = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
if ($null -eq $rule) { Stop-Run "firewall rule $RuleName is missing; run setup-device-proxy.ps1" }
if (-not (Test-ProxyFirewall $rule $port)) {
    Stop-Run "firewall rule $RuleName must allow inbound TCP $port from LocalSubnet4 on all profiles with unrestricted interfaces; run setup-device-proxy.ps1"
}
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    Stop-Run "port $port is already in use; stop the old proxy or wait for its container watch to finish"
}
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Installed`" -ConfigDirectory `"$ConfigDirectory`" -ListenAddress $gateway -Distro `"$Distro`""
$process = Start-Process -FilePath $PowerShell -ArgumentList $arguments -WorkingDirectory $ConfigDirectory -WindowStyle Hidden -PassThru
$answered = $false
foreach ($attempt in 1..20) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { break }
    foreach ($workspace in @($config.workspaces)) {
        $client = $null
        try {
            $connection = Get-Content -Raw -LiteralPath (Join-Path $workspace ".pico-device-proxy.json") | ConvertFrom-Json
            if ($connection.host -cne $gateway -or $connection.port -ne $port) { continue }
            $client = New-Object System.Net.Sockets.TcpClient
            if (-not $client.ConnectAsync($gateway, $port).Wait(1000)) { continue }
            $stream = $client.GetStream(); $stream.ReadTimeout = 1000
            $writer = New-Object System.IO.StreamWriter($stream)
            $writer.WriteLine((@{ cmd = "allowed"; serial = ""; token = $connection.token } | ConvertTo-Json -Compress)); $writer.Flush()
            $reader = New-Object System.IO.StreamReader($stream)
            $reply = $reader.ReadLine() | ConvertFrom-Json
            $answered = $reply.ok -eq $true -and $reply.allowed -eq $false
        } catch { $answered = $false } finally { if ($null -ne $client) { $client.Close() } }
        if ($answered) { break }
    }
    if ($answered) { break }
}
if (-not $answered) {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id }
    Stop-Run "installed proxy did not answer on ${gateway}:$port; run $Installed in the foreground to inspect its error"
}
Write-Output "ok: proxy answers on ${gateway}:$port; the container can now be opened"
Write-Output "open the configured workspace in an ordinary Windows VS Code window with executeInWSL and executeInWSLDistro=$Distro"
exit 0
