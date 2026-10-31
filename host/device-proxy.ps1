# SPDX-License-Identifier: MIT
# Windows PowerShell 5.1 device transport (AR-15). The installed copy enforces
# host allow-list and workspace-relative load paths; sequencing stays in Python.
# -ListenAddress is one IPv4 address, defaulting to loopback for no-device CI.
# -Distro enables the container watch: wait five minutes for the first matching
# dev container, then stop when none is running. Connection files carry host,
# port and token, and are removed on exit. -ContainerQuery is the injected query
# seam for the no-WSL lifecycle test; the launcher uses the real docker query.
# -List enumerates once without a listener, serial open, copy or token write.
# device-proxy.json holds port/workspaces; devices.toml is the host allow-list.
# Exit status: 0 listed/stopped; 2 unable to list/start/watch.

param(
    [string] $ConfigDirectory = (Join-Path $env:APPDATA "pico"),
    [switch] $List,
    [string] $ListenAddress = "127.0.0.1",
    [string] $Distro = "",
    [scriptblock] $ContainerQuery
)

$ErrorActionPreference = "Stop"
$ConnectionFile = ".pico-device-proxy.json"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$LogPath = Join-Path $ConfigDirectory "device-proxy.log"

function Write-Log([string] $Message) {
    $line = "{0} {1}`r`n" -f (Get-Date).ToUniversalTime().ToString("o"), $Message
    [System.IO.File]::AppendAllText($LogPath, $line, $Utf8)
}

function Stop-Run([string] $Message) {
    Write-Output "STOP: $Message"
    exit 2
}

# One enumeration implementation serves read-only CLI and request runspaces.
$boardFunctions = {
    # The allow-list: devices.toml, read at every request. A line this reader
    # does not understand makes the whole file allow nothing.
    function Get-AllowedSerials {
        $path = Join-Path $state.ConfigDirectory "devices.toml"
        $found = @()
        $row = $false
        $serialSeen = $false
        $labelSeen = $false
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return @() }
        foreach ($line in (Get-Content -LiteralPath $path)) {
            $text = $line.Trim()
            if ($text -eq "" -or $text.StartsWith("#")) { continue }
            if ($text -eq "[[device]]") {
                if ($row -and -not $serialSeen) { return @() }
                $row = $true; $serialSeen = $false; $labelSeen = $false
                continue
            }
            if (-not $row) { return @() }
            if ($text -match '^serial\s*=\s*"([^"\\]+)"\s*(#.*)?$' -and -not $serialSeen) {
                $found += $Matches[1]; $serialSeen = $true; continue
            }
            if ($text -match '^label\s*=\s*"[^"\\]*"\s*(#.*)?$' -and -not $labelSeen) {
                $labelSeen = $true; continue
            }
            return @()
        }
        if ($row -and -not $serialSeen) { return @() }
        return $found
    }

    # The last segment of the USB device's instance identifier is its USB serial
    # when the device reports one and location information otherwise (Microsoft,
    # Instance IDs); a serial port is either that device or its interface.
    function Get-UsbSerial([string] $instance) {
        if ($instance -match '^USB\\VID_2E8A&PID_[0-9A-Fa-f]{4}\\([^\\]+)$') { return $Matches[1] }
        return $null
    }

    function Get-Boards {
        $allowed = @(Get-AllowedSerials)
        $boards = @()
        $ports = @{}
        $entities = @(Get-CimInstance -ClassName Win32_PnPEntity -Filter "PNPDeviceID LIKE 'USB%VID_2E8A%'")
        foreach ($entity in $entities) {
            if ($entity.Name -match '\((COM[0-9]+)\)') { $port = $Matches[1] } else { continue }
            $serial = Get-UsbSerial $entity.PNPDeviceID
            if ($null -eq $serial) {
                try {
                    $parent = (Get-PnpDeviceProperty -InstanceId $entity.PNPDeviceID -KeyName "DEVPKEY_Device_Parent").Data
                    $serial = Get-UsbSerial ([string] $parent)
                } catch { continue }
            }
            if ($null -eq $serial) { continue }
            if (-not $ports.ContainsKey($serial)) { $ports[$serial] = @() }
            $ports[$serial] += $port
        }
        foreach ($serial in $ports.Keys) {
            $boards += @{
                serial = $serial; product = ""; ports = @($ports[$serial]); bootloader = $false
                drive = $null; listed = ($allowed -ccontains $serial)
            }
        }
        # Resolve a UF2 drive through its device parents to the Pico USB serial.
        # Disk instance identifiers can contain composite-device prefixes.
        foreach ($disk in @(Get-CimInstance -ClassName Win32_LogicalDisk)) {
            if ($disk.DriveType -ne 2 -and $disk.DriveType -ne 3) { continue }
            $drive = [string] $disk.DeviceID
            if (-not (Test-Path -LiteralPath ($drive + "\INFO_UF2.TXT") -PathType Leaf)) { continue }
            $serial = ""
            $partition = @(Get-CimAssociatedInstance -InputObject $disk -Association Win32_LogicalDiskToPartition)
            if ($partition.Count -eq 1) {
                $physical = @(Get-CimAssociatedInstance -InputObject $partition[0] -Association Win32_DiskDriveToDiskPartition)
                if ($physical.Count -eq 1) {
                    $instance = [string] $physical[0].PNPDeviceID
                    for ($level = 0; $level -le 4; $level++) {
                        $usbSerial = Get-UsbSerial $instance
                        if (-not [string]::IsNullOrEmpty($usbSerial)) {
                            $serial = $usbSerial
                            break
                        }
                        if ($level -eq 4) { break }
                        try {
                            $instance = [string] (Get-PnpDeviceProperty -InstanceId $instance -KeyName "DEVPKEY_Device_Parent").Data
                        } catch { break }
                        if ([string]::IsNullOrEmpty($instance)) { break }
                    }
                }
            }
            $boards += @{
                serial = $serial; product = ""; ports = @(); bootloader = $true
                drive = $drive; listed = ($serial -ne "" -and ($allowed -ccontains $serial))
            }
        }
        return $boards
    }
}

if ($List) {
    try {
        $state = @{ ConfigDirectory = $ConfigDirectory }
        . $boardFunctions
        ConvertTo-Json -InputObject @(Get-Boards) -Depth 6
        exit 0
    } catch {
        [Console]::Error.WriteLine("cannot list boards: $($_.Exception.Message)")
        exit 2
    }
}

# A wildcard would expose more interfaces than the selected address.
$listenIp = $null
if (-not [System.Net.IPAddress]::TryParse($ListenAddress, [ref] $listenIp) -or
    $listenIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
    $listenIp.ToString() -cne $ListenAddress -or
    $listenIp.Equals([System.Net.IPAddress]::Any) -or
    $listenIp.Equals([System.Net.IPAddress]::Broadcast) -or
    ($listenIp.GetAddressBytes()[0] -ge 224 -and $listenIp.GetAddressBytes()[0] -le 239)) {
    Stop-Run "ListenAddress must be one unicast IPv4 literal"
}

# The query is the only WSL dependency of the lifetime decision (AR-15).
function Test-ContainerLifetime([scriptblock] $Query, [string[]] $Workspaces,
    [ref] $Seen, [double] $Elapsed, [int] $WaitSeconds = 300) {
    foreach ($workspace in $Workspaces) {
        if (& $Query $workspace) { $Seen.Value = $true; return $true }
    }
    return -not $Seen.Value -and $Elapsed -lt $WaitSeconds
}

if ($Distro -and $null -eq $ContainerQuery) {
    $ContainerQuery = {
        param($workspace)
        # --cd avoids translating a Windows working directory with drives off.
        # The label filter has no embedded quotes; --exec bypasses the shell.
        $ids = @(& wsl.exe --cd / -d $Distro --exec docker ps -q --filter "label=devcontainer.local_folder=$workspace" 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "Docker container query failed in ${Distro}: $($ids -join ' ')" }
        return @($ids | Where-Object { -not [string]::IsNullOrWhiteSpace([string] $_) }).Count -gt 0
    }
}

# Pre-flight: the configuration, the workspaces, the port.
$configPath = Join-Path $ConfigDirectory "device-proxy.json"
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    Stop-Run "$configPath not found; run setup-device-proxy.ps1 first"
}
try {
    $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
    $port = [int] $config.port
    $roots = @($config.workspaces | ForEach-Object { [System.IO.Path]::GetFullPath([string] $_) })
} catch {
    Stop-Run "$configPath is not a valid configuration: $($_.Exception.Message)"
}
if ($port -lt 1 -or $port -gt 65535) { Stop-Run "port must be between 1 and 65535" }
if ($roots.Count -eq 0) { Stop-Run "$configPath names no workspace" }
foreach ($root in $roots) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        Stop-Run "workspace $root does not exist"
    }
}

$tokens = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
foreach ($root in $roots) {
    $bytes = New-Object byte[] 32
    $random.GetBytes($bytes)
    $tokens[([BitConverter]::ToString($bytes) -replace "-", "").ToLower()] = $root
}
$random.Dispose()

try {
    $listener = New-Object System.Net.Sockets.TcpListener($listenIp, $port)
    $listener.Start()
} catch {
    Stop-Run "cannot listen on ${ListenAddress}:${port}: $($_.Exception.Message)"
}

$written = @()

# One request per connection, run in its own runspace so that a console held
# open does not stop a list or a load.
$handler = {
    param($client, $state)
    $ErrorActionPreference = "Stop"
    $utf8 = New-Object System.Text.UTF8Encoding($false)

    function Send-Reply($stream, $reply) {
        $bytes = $utf8.GetBytes(($reply | ConvertTo-Json -Compress -Depth 6) + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
    }

    function Send-Refusal($stream, [string] $code, [string] $text) {
        Send-Reply $stream @{ ok = $false; code = $code; error = $text }
    }

    function Read-Line($stream) {
        $buffer = New-Object System.Collections.Generic.List[byte]
        while ($true) {
            $byte = $stream.ReadByte()
            if ($byte -lt 0) { return $null }
            if ($byte -eq 10) { break }
            if ($buffer.Count -ge 65535) { return $null }
            $buffer.Add([byte] $byte)
        }
        return $utf8.GetString($buffer.ToArray())
    }

    . ([scriptblock]::Create($state.BoardFunctions))

    function Test-WorkspacePath([string] $root, [string] $relative) {
        if ($relative -eq "" -or $relative -match '^[\\/]' -or $relative.Contains(":")) { return $null }
        if ($relative.IndexOfAny([System.IO.Path]::GetInvalidPathChars()) -ge 0) { return $null }
        foreach ($segment in ($relative -split '[\\/]')) {
            if ($segment -eq ".." -or $segment -eq "") { return $null }
        }
        # Combine lexically so UNC workspaces need no PowerShell drive mapping.
        $full = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($root, ($relative -replace "/", "\")))
        $prefix = $root.TrimEnd("\") + "\"
        if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return $null }
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { return $null }
        # Refuse links/junctions at every component, including workspace parents.
        # FullPath alone only removes dot segments; it does not resolve links.
        $item = Get-Item -LiteralPath $full -Force
        while ($null -ne $item) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return $null }
            if ($item -is [System.IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
        }
        return $full
    }

    try {
        $stream = $client.GetStream()
        $stream.ReadTimeout = 5000
        $line = Read-Line $stream
        if ($null -eq $line) { return }
        try { $request = $line | ConvertFrom-Json } catch { $request = $null }
        if ($null -eq $request) { Send-Refusal $stream "request" "the request is not JSON"; return }
        $root = $null
        if ($request.token -is [string] -and $state.Tokens.ContainsKey($request.token)) {
            $root = $state.Tokens[$request.token]
        }
        if ($null -eq $root) { Send-Refusal $stream "token" "bad token"; return }
        $command = [string] $request.cmd
        $serial = [string] $request.serial

        if ($command -eq "list") {
            Send-Reply $stream @{ ok = $true; boards = @(Get-Boards) }
            return
        }
        if ($command -eq "allowed") {
            Send-Reply $stream @{ ok = $true; allowed = ((@(Get-AllowedSerials)) -ccontains $serial) }
            return
        }
        if ($command -ne "open" -and $command -ne "load") {
            Send-Refusal $stream "request" "unknown command $command"
            return
        }
        if ($serial -eq "" -or -not ((@(Get-AllowedSerials)) -ccontains $serial)) {
            Send-Refusal $stream "denied" "$serial is not in the host allow-list"
            return
        }

        if ($command -eq "load") {
            try { $full = Test-WorkspacePath $root ([string] $request.path) } catch { $full = $null }
            if ($null -eq $full) {
                Send-Refusal $stream "path" "$($request.path) is not a file inside the workspace"
                return
            }
            $found = @(Get-Boards | Where-Object { $_.bootloader -and $_.serial -ceq $serial })
            if ($found.Count -ne 1) {
                Send-Refusal $stream "absent" "no bootloader drive is tied to $serial"
                return
            }
            $board = $found[0]
            $target = Join-Path ($board.drive + "\") ([System.IO.Path]::GetFileName($full))
            try {
                [System.IO.File]::Copy($full, $target, $true)
            } catch {
                Send-Refusal $stream "failed" "the copy to $($board.drive) failed: $($_.Exception.Message)"
                return
            }
            Send-Reply $stream @{ ok = $true }
            return
        }

        # open: the serial port of this board, at the given baud rate.
        $found = @(Get-Boards | Where-Object { -not $_.bootloader -and $_.serial -ceq $serial })
        $board = if ($found.Count -eq 1) { $found[0] } else { $null }
        $name = [string] $request.port
        if ($null -eq $board -or -not (@($board.ports) -contains $name)) {
            Send-Refusal $stream "absent" "$name is not a port of $serial"
            return
        }
        $baud = 0
        if (-not [int]::TryParse([string] $request.baud, [ref] $baud) -or $baud -lt 300 -or $baud -gt 4000000) {
            Send-Refusal $stream "request" "baud rate $baud is out of range"
            return
        }
        $serialPort = New-Object System.IO.Ports.SerialPort $name, $baud
        $serialPort.DtrEnable = $true
        $serialPort.RtsEnable = $true
        try {
            $serialPort.Open()
        } catch [System.UnauthorizedAccessException] {
            Send-Refusal $stream "busy" "$name is in use or access to it is denied"
            return
        } catch {
            Send-Refusal $stream "failed" "cannot open ${name}: $($_.Exception.Message)"
            return
        }
        try {
            Send-Reply $stream @{ ok = $true }
            $stream.ReadTimeout = [System.Threading.Timeout]::Infinite
            $wire = $serialPort.BaseStream
            $buffer = New-Object byte[] 4096
            while ($true) {
                $moved = $false
                if ($serialPort.BytesToRead -gt 0) {
                    $count = $wire.Read($buffer, 0, [Math]::Min($buffer.Length, $serialPort.BytesToRead))
                    if ($count -gt 0) { $stream.Write($buffer, 0, $count); $stream.Flush(); $moved = $true }
                }
                if ($stream.DataAvailable) {
                    $count = $stream.Read($buffer, 0, $buffer.Length)
                    if ($count -le 0) { break }
                    $wire.Write($buffer, 0, $count)
                    $moved = $true
                } elseif ($client.Client.Poll(0, [System.Net.Sockets.SelectMode]::SelectRead)) {
                    break
                }
                if (-not $moved) { Start-Sleep -Milliseconds 5 }
            }
        } finally {
            $serialPort.Close()
        }
    } catch {
        [System.IO.File]::AppendAllText($state.LogPath, "request failed: $($_.Exception.Message)`r`n")
    } finally {
        $client.Close()
    }
}.ToString()

$state = [hashtable]::Synchronized(@{ Tokens = $tokens; ConfigDirectory = $ConfigDirectory; LogPath = $LogPath; BoardFunctions = $boardFunctions.ToString() })
$pool = [runspacefactory]::CreateRunspacePool(1, 16)
$pool.Open()
$running = New-Object System.Collections.ArrayList
$exitStatus = 0
try {
    foreach ($token in $tokens.Keys) {
        $file = Join-Path $tokens[$token] $ConnectionFile
        $text = [ordered]@{ host = $ListenAddress; port = $port; token = $token } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($file, $text, $Utf8)
        $written += $file
    }
    Write-Log "listening on ${ListenAddress}:$port for $($roots.Count) workspace(s)"
    Write-Output "listening on ${ListenAddress}:$port"
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $nextCheck = 0
    $seenContainer = $false
    while ($true) {
        if ($Distro -and $watch.Elapsed.TotalSeconds -ge $nextCheck) {
            if (-not (Test-ContainerLifetime $ContainerQuery $roots ([ref] $seenContainer) $watch.Elapsed.TotalSeconds)) {
                Write-Log "no matching dev container; stopped"
                break
            }
            $nextCheck = $watch.Elapsed.TotalSeconds + 3
        }
        if ($listener.Pending()) {
            $client = $listener.AcceptTcpClient()
            $shell = [powershell]::Create()
            $shell.RunspacePool = $pool
            [void] $shell.AddScript($handler).AddArgument($client).AddArgument($state)
            [void] $running.Add(@{ Shell = $shell; Result = $shell.BeginInvoke() })
        } else { Start-Sleep -Milliseconds 100 }
        foreach ($job in @($running | Where-Object { $_.Result.IsCompleted })) {
            $job.Shell.EndInvoke($job.Result)
            $job.Shell.Dispose()
            $running.Remove($job)
        }
    }
} catch {
    Write-Output "STOP: device proxy: $($_.Exception.Message)"
    $exitStatus = 2
} finally {
    $listener.Stop()
    foreach ($file in $written) { Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue }
    foreach ($job in $running) { $job.Shell.Stop(); $job.Shell.Dispose() }
    $pool.Close()
    $pool.Dispose()
}
exit $exitStatus
