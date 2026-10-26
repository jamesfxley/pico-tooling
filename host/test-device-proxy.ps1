# SPDX-License-Identifier: MIT
# AR-15: native no-device acceptance; no WSL distro or firewall elevation.
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSEdition -ne "Desktop" -or $PSVersionTable.PSVersion.Major -ne 5) { throw "Run with Windows PowerShell 5.1" }
$root = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
$config = Join-Path $root "config"
$startup = Join-Path $root "startup"
$workspace = Join-Path $root "workspace"
New-Item -ItemType Directory -Path $startup, $workspace | Out-Null
$probe = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
$probe.Start(); $port = $probe.LocalEndpoint.Port; $probe.Stop()
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$setup = Join-Path $PSScriptRoot "setup-device-proxy.ps1"
$proxySource = Join-Path $PSScriptRoot "device-proxy.ps1"
$installed = Join-Path $config "device-proxy.ps1"
$tokenFile = Join-Path $workspace ".pico-device-proxy.json"
$shortcut = Join-Path $startup "pico-device-proxy.lnk"
$process = $null

# Parse all entry points with the actual PS 5.1 parser, then exercise the exact
# production functions rather than maintaining another path/lifetime model.
foreach ($file in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.ps1")) {
    $parseTokens = $null; $parseErrors = $null
    [void] [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref] $parseTokens, [ref] $parseErrors)
    if (@($parseErrors).Count -ne 0) { throw "$($file.Name): $parseErrors" }
}
function Get-ProxyFunction([string] $Name, [string] $Source = $proxySource) {
    $parseTokens = $null; $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref] $parseTokens, [ref] $parseErrors)
    $functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $Name }, $true))
    if ($functions.Count -ne 1) { throw "Expected one $Name" }
    return [scriptblock]::Create($functions[0].Extent.Text)
}
function Test-UncPaths {
    . (Get-ProxyFunction "Test-WorkspacePath")
    $unc = '\\wsl.localhost\pico-dev\home\fixture\repo'
    $expected = $unc + '\build\image.uf2'
    function Test-Path { param($LiteralPath, $PathType) return $LiteralPath -ceq $expected }
    function Get-Item { param($LiteralPath, [switch] $Force) return [pscustomobject]@{ Attributes = 0; Parent = $null } }
    if ((Test-WorkspacePath $unc 'build/image.uf2') -cne $expected) { throw "UNC workspace file was refused" }
    foreach ($relative in @('../repo-sibling/image.uf2', '\\wsl.localhost\pico-dev\home\fixture\repo-sibling\image.uf2', 'C:\outside.uf2')) {
        if ($null -ne (Test-WorkspacePath $unc $relative)) { throw "Traversal/sibling/rooted path was accepted: $relative" }
    }
}
Test-UncPaths
. (Get-ProxyFunction "Test-ContainerLifetime")
$seen = $false
if (-not (Test-ContainerLifetime { $false } @('one') ([ref] $seen) 299)) { throw "Initial wait ended early" }
if (Test-ContainerLifetime { $false } @('one') ([ref] $seen) 300) { throw "Initial wait exceeded its bound" }
if (-not (Test-ContainerLifetime { param($name) $name -ceq 'two' } @('one', 'two') ([ref] $seen) 1)) { throw "Any-workspace container was missed" }
if (Test-ContainerLifetime { $false } @('one', 'two') ([ref] $seen) 2) { throw "Watch continued after the last container stopped" }
try {
    [void] (Test-ContainerLifetime { throw "query fixture failure" } @('one') ([ref] $seen) 1)
    throw "A failed query was treated as an empty result"
} catch { if ($_.Exception.Message -cne "query fixture failure") { throw } }


# AR-15: both entry points validate the production predicate without a firewall.
function Test-FirewallScope([string] $Source) {
    . (Get-ProxyFunction "Test-ProxyFirewall" $Source)
    $fixture = @{
        Rule = [pscustomobject]@{ Enabled = "True"; Direction = "Inbound"; Action = "Allow"; Profile = "Any" }
        Ports = [pscustomobject]@{ Protocol = "TCP"; LocalPort = "47600"; RemotePort = "Any" }
        Addresses = [pscustomobject]@{ LocalAddress = @("Any"); RemoteAddress = @("LocalSubnet4") }
        Interfaces = [pscustomobject]@{ InterfaceAlias = @("Any") }
        Types = [pscustomobject]@{ InterfaceType = "Any" }
    }
    function Get-NetFirewallPortFilter { return $fixture.Ports }
    function Get-NetFirewallAddressFilter { return $fixture.Addresses }
    function Get-NetFirewallInterfaceFilter { return $fixture.Interfaces }
    function Get-NetFirewallInterfaceTypeFilter { return $fixture.Types }
    if (-not (Test-ProxyFirewall $fixture.Rule 47600)) { throw "$Source refused the expected firewall scope" }
    $fixture.Ports.Protocol = "6"
    if (-not (Test-ProxyFirewall $fixture.Rule 47600)) { throw "$Source refused TCP protocol number" }
    $fixture.Ports.Protocol = "TCP"
    if (Test-ProxyFirewall $null 47600) { throw "$Source accepted an absent rule" }
    foreach ($case in @(
        @{ Target = "Rule"; Property = "Enabled"; Value = "False" },
        @{ Target = "Rule"; Property = "Direction"; Value = "Outbound" },
        @{ Target = "Rule"; Property = "Action"; Value = "Block" },
        @{ Target = "Rule"; Property = "Profile"; Value = "Private" },
        @{ Target = "Ports"; Property = "Protocol"; Value = "UDP" },
        @{ Target = "Ports"; Property = "LocalPort"; Value = "47601" },
        @{ Target = "Ports"; Property = "RemotePort"; Value = "80" },
        @{ Target = "Addresses"; Property = "LocalAddress"; Value = @("127.0.0.1") },
        @{ Target = "Addresses"; Property = "RemoteAddress"; Value = @("Any") },
        @{ Target = "Addresses"; Property = "RemoteAddress"; Value = @("LocalSubnet") },
        @{ Target = "Addresses"; Property = "RemoteAddress"; Value = @("LocalSubnet4", "192.0.2.1") },
        @{ Target = "Interfaces"; Property = "InterfaceAlias"; Value = @("vEthernet (WSL (Hyper-V firewall))") },
        @{ Target = "Interfaces"; Property = "InterfaceAlias"; Value = @("e7798a11-8632-412b-9da1-e50c3a501347") },
        @{ Target = "Interfaces"; Property = "InterfaceAlias"; Value = @("Any", "Ethernet") },
        @{ Target = "Types"; Property = "InterfaceType"; Value = "Wired" }
    )) {
        $part = $fixture[$case.Target]; $before = $part.($case.Property)
        $part.($case.Property) = $case.Value
        if (Test-ProxyFirewall $fixture.Rule 47600) { throw "$Source accepted restricted/broader $($case.Target).$($case.Property)" }
        $part.($case.Property) = $before
    }
}
Test-FirewallScope $setup
Test-FirewallScope (Join-Path $PSScriptRoot "start-device-proxy.ps1")

function Wait-Connection {
    foreach ($attempt in 1..100) {
        if ($process.HasExited) { throw "Proxy exited before publishing a connection" }
        if (Test-Path -LiteralPath $tokenFile -PathType Leaf) { return Get-Content -Raw -LiteralPath $tokenFile | ConvertFrom-Json }
        Start-Sleep -Milliseconds 100
    }
    throw "Proxy did not publish its connection"
}
function Request($request) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $port)
        $stream = $client.GetStream(); $stream.ReadTimeout = 10000
        $writer = New-Object System.IO.StreamWriter($stream)
        $writer.WriteLine(($request | ConvertTo-Json -Compress)); $writer.Flush()
        $reader = New-Object System.IO.StreamReader($stream)
        return $reader.ReadLine() | ConvertFrom-Json
    } finally { $client.Close() }
}
try {
    $output = & $powershell -NoProfile -ExecutionPolicy Bypass -File $setup -NoFirewall -Workspace $workspace -Port $port -ConfigDirectory $config -StartupDirectory $startup
    if ($LASTEXITCODE -ne 0) { throw "Setup failed: $output" }
    if ((Test-Path -LiteralPath $shortcut) -or (Test-Path -LiteralPath $tokenFile)) { throw "Setup started a proxy or made a shortcut" }
    # Updates remove, and name, the prior setup's shortcut.
    [System.IO.File]::WriteAllText($shortcut, "old setup fixture")
    $output = & $powershell -NoProfile -ExecutionPolicy Bypass -File $setup -NoFirewall -Workspace $workspace -ConfigDirectory $config -StartupDirectory $startup
    if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $shortcut) -or -not (($output -join "`n").Contains($shortcut))) { throw "Old shortcut was not removed and named" }
    $acl = Get-Acl -LiteralPath $config
    $rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 1 -or
        $rules[0].IdentityReference -ne $identity -or $rules[0].AccessControlType -ne "Allow" -or
        $rules[0].FileSystemRights -ne "FullControl" -or $rules[0].InheritanceFlags -ne "ContainerInherit,ObjectInherit" -or
        $rules[0].PropagationFlags -ne "None") { throw "Unexpected configuration access rules" }
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$installed`" -ConfigDirectory `"$config`""
    $process = Start-Process -FilePath $powershell -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $connection = Wait-Connection
    if ($connection.host -cne "127.0.0.1" -or $connection.port -ne $port -or $connection.token -cnotmatch '^[a-f0-9]{64}$') { throw "Invalid connection file" }
    $reply = Request @{ cmd = "list"; token = $connection.token }
    if ($reply.ok -ne $true -or $null -eq $reply.boards -or @($reply.boards).Count -ne 0) { throw "Expected an empty authenticated device list" }
    $reply = Request @{ cmd = "list" }
    if ($reply.ok -ne $false -or $reply.code -ne "token") { throw "Unauthenticated list was not refused" }
    Stop-Process -Id $process.Id; $process.WaitForExit(); Remove-Item -LiteralPath $tokenFile
    # A real listener loop exits normally on the injected container query.
    $escapedProxy = $installed.Replace("'", "''"); $escapedConfig = $config.Replace("'", "''")
    $code = "`$counter=@{calls=0}; `$query={param(`$workspace) `$counter.calls+=1; return `$counter.calls -eq 1}.GetNewClosure(); & '$escapedProxy' -ConfigDirectory '$escapedConfig' -Distro fixture -ContainerQuery `$query"
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($code))
    $process = Start-Process -FilePath $powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded" -WindowStyle Hidden -PassThru
    [void] (Wait-Connection)
    if (-not $process.WaitForExit(10000) -or $process.ExitCode -ne 0) { throw "Container lifetime did not end normally" }
    if (Test-Path -LiteralPath $tokenFile) { throw "Connection file survived normal lifetime exit" }
} finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id; $process.WaitForExit() }
    & $powershell -NoProfile -ExecutionPolicy Bypass -File $setup -Remove -NoFirewall -ConfigDirectory $config -StartupDirectory $startup
    if ($LASTEXITCODE -ne 0) { throw "Proxy removal failed: $LASTEXITCODE" }
}
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Listener survived removal" }
if ((Test-Path -LiteralPath $tokenFile) -or (Test-Path -LiteralPath $shortcut) -or
    (Test-Path -LiteralPath $installed) -or (Test-Path -LiteralPath (Join-Path $config "start-device-proxy.ps1"))) { throw "Installed files survived removal" }
Remove-Item -Recurse -Force -LiteralPath $root
Write-Output "PASS: setup, access rules, explicit host, token/list refusal, UNC bounds and container lifetime"
