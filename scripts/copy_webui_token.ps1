param([Parameter(Mandatory=$true)][string]$Server)
$ErrorActionPreference = 'Stop'
# Use your existing SSH authentication. Never prints the captured credential.
# Keep the remote command shell-safe: the previous nested Python quoting was
# stripped by OpenSSH's remote shell, causing an empty/invalid command.
$remoteScript = "sed -n 's/^WEBUI_TOKEN=//p' /home/example-user/qq-ai-bot/.env"
$webuiCredential = & ssh $Server $remoteScript
if ($LASTEXITCODE -ne 0 -or -not $webuiCredential) { throw 'Unable to read WebUI token using existing SSH authentication.' }
$webuiCredential = ($webuiCredential -join '').Trim()
if (-not $webuiCredential) { throw 'WebUI token was empty; no clipboard value was changed.' }
Set-Clipboard -Value $webuiCredential
Write-Host 'WebUI token copied to clipboard. Paste into the local WebUI login field; clear the clipboard after login.'
$webuiCredential = $null
