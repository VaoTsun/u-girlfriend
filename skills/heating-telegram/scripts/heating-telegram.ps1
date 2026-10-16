# scripts/heating-telegram.ps1
# Берёт сводку датчика (по умолчанию "отопление") навыка heating-check
# и отправляет её в Telegram через Bot API.
#
# Примеры:
#   powershell -File heating-telegram.ps1 -Preset отопление -Minutes 5
#   powershell -File heating-telegram.ps1 -Preset котельная -Minutes 30
#   powershell -File heating-telegram.ps1 -Preset отопление -DryRun   # без отправки
param(
  [string]$Preset = "отопление",
  [int]$Minutes = 5,
  [string]$Server = "",
  [string]$Token = "",
  [string]$ChatId = "",
  [string]$ConfigPath = "",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path   # ...\skills\heating-telegram\scripts
$skillDir = Split-Path -Parent $here                       # ...\skills\heating-telegram
$skillsDir = Split-Path -Parent $skillDir                  # ...\skills

if (-not $ConfigPath) { $ConfigPath = Join-Path $skillDir "config.json" }

# --- читаем конфиг (token / chat_id / server) ---
if (Test-Path $ConfigPath) {
  try {
    $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Token)  { $Token  = [string]$cfg.token }
    if (-not $ChatId) { $ChatId = [string]$cfg.chat_id }
    if (-not $Server -and $cfg.server) { $Server = [string]$cfg.server }
  } catch {
    Write-Output "Ошибка: не удалось прочитать конфиг $ConfigPath : $($_.Exception.Message)"
    exit 2
  }
}
if (-not $Server) { $Server = "192.168.88.171:90" }
if (-not $Token)  { Write-Output "Ошибка: не задан токен бота (config.json → token)."; exit 2 }
if (-not $ChatId) { Write-Output "Ошибка: не задан chat_id (config.json → chat_id)."; exit 2 }

# --- берём сводку у навыка heating-check ---
$heating = Join-Path $skillsDir "heating-check\scripts\heating.ps1"
if (-not (Test-Path $heating)) {
  Write-Output "Ошибка: не найден heating.ps1 ($heating)."
  exit 3
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "powershell.exe"
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $heating + '" -Preset "' + $Preset + '" -Minutes ' + $Minutes + ' -Server "' + $Server + '"'
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
try { $psi.StandardOutputEncoding = New-Object Text.UTF8Encoding $false } catch {}
try { $psi.StandardErrorEncoding  = New-Object Text.UTF8Encoding $false } catch {}
$psi.CreateNoWindow = $true

$p = [System.Diagnostics.Process]::Start($psi)
$text = $p.StandardOutput.ReadToEnd()
$err  = $p.StandardError.ReadToEnd()
$p.WaitForExit()
$text = ($text).Trim()
if (-not $text) { $text = ($err).Trim() }
if (-not $text) { Write-Output "Ошибка: датчик не вернул данных."; exit 4 }

# --- формируем сообщение ---
$stamp = Get-Date -Format "dd.MM.yyyy HH:mm"
$escPreset = $Preset -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;'
$escText   = $text    -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;'
# убираем первую строку-заголовок "Устройство: ..." — она дублирует <b>-заголовок
$lines = $escText -split "`r?`n"
if ($lines.Count -gt 1 -and $lines[0] -match '^\s*Устройство:') {
  $escText = ($lines[1..($lines.Count - 1)] -join "`n").Trim()
}
$msg = "<b>$escPreset</b> ($stamp)`n<pre>$escText</pre>"

if ($DryRun) {
  Write-Output "DRYRUN: сообщение сформировано, но не отправлено."
  Write-Output $msg
  exit 0
}

# --- отправляем в Telegram ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$uri = "https://api.telegram.org/bot$Token/sendMessage"
$body = "chat_id=" + [uri]::EscapeDataString($ChatId) +
        "&parse_mode=HTML&disable_web_page_preview=true&text=" + [uri]::EscapeDataString($msg)

try {
  $resp = Invoke-RestMethod -Method Post -Uri $uri -Body $body `
            -ContentType "application/x-www-form-urlencoded; charset=utf-8" -TimeoutSec 30
} catch {
  Write-Output "Ошибка отправки в Telegram: $($_.Exception.Message)"
  exit 5
}

if ($resp.ok) {
  $now = ([regex]::Match($text, 'Сейчас:\s*([-\d.,]+)')).Groups[1].Value
  if ($now) {
    Write-Output "Отправлено в Telegram: $Preset, сейчас $now."
  } else {
    Write-Output "Отправлено в Telegram: $Preset."
  }
} else {
  Write-Output "Ошибка отправки в Telegram: $($resp.description)"
  exit 5
}
