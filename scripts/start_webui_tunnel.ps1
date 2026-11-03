[CmdletBinding()]
param(
    # Use the existing Windows SSH authentication, for example ubuntu@203.0.113.10.
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^\s@]+@[^\s@]+$')]
    [string]$Server,

    [ValidateRange(1, 65535)]
    [int]$LocalPort = 6099,

    [ValidateRange(1, 65535)]
    [int]$RemotePort = 6099,

    [ValidateRange(1, 300)]
    [int]$InitialDelaySeconds = 5,

    [ValidateRange(1, 300)]
    [int]$MaxDelaySeconds = 60
)

$ErrorActionPreference = 'Stop'

function Get-LocalListener {
    try {
        @(Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction Stop)
    }
    catch {
        # Older PowerShell versions may not expose Get-NetTCPConnection. In that
        # case ssh itself will report a bind failure without changing the server.
        @()
    }
}

$listeners = @(Get-LocalListener)
if ($listeners.Count -gt 0) {
    $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Local port $LocalPort is already listening (PID $owners). Close the existing tunnel or choose -LocalPort; no process was stopped."
}

$forward = "127.0.0.1`:$LocalPort`:127.0.0.1`:$RemotePort"
$sshArgs = @(
    '-N',
    '-T',
    '-L', $forward,
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'TCPKeepAlive=yes',
    '-o', 'ConnectTimeout=10',
    '-o', 'BatchMode=yes',
    '-o', 'LogLevel=ERROR',
    $Server
)

$delay = $InitialDelaySeconds
$attempt = 0
Write-Host "WebUI tunnel: local http://127.0.0.1:$LocalPort/webui/ -> server loopback port $RemotePort"
Write-Host 'The tunnel reconnects after a transient network drop. Press Ctrl+C to stop it.'

try {
    while ($true) {
        $attempt++
        Write-Host "SSH connection attempt $attempt..."
        & ssh @sshArgs
        $exitCode = $LASTEXITCODE

        # A clean close is still followed by a reconnect: this keeps the helper
        # useful when a laptop wakes from sleep or Wi-Fi changes networks.
        Write-Warning "SSH tunnel exited with code $exitCode; retrying in $delay seconds."
        Start-Sleep -Seconds $delay
        $delay = [Math]::Min($delay * 2, $MaxDelaySeconds)
    }
}
finally {
    Write-Host 'WebUI tunnel stopped.'
}
