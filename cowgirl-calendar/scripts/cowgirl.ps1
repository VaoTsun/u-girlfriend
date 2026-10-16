# scripts/cowgirl.ps1
# Календарь ковбойши — напоминания о сельхозработах в Telegram.
# Каждое утро (задача Планировщика cowgirl-calendar) сверяет calendar.txt
# с сегодняшней датой и шлёт в Telegram работы, у которых сегодня первый день
# напоминания (одна работа — одно напоминание в год, повторно не шлёт).
#
# Запуск вручную:
#   powershell -File cowgirl.ps1            # обычный цикл
#   powershell -File cowgirl.ps1 -DryRun    # показать, что уйдёт, без отправки
#   powershell -File cowgirl.ps1 -Force     # показать ВСЕ работы сезона (без отправки, игнор state)
param(
  [switch]$DryRun,
  [switch]$Force,          # не трогает state, печатает работы на сегодня как есть
  [string]$CalendarPath = "",
  [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}

$here      = Split-Path -Parent $MyInvocation.MyCommand.Path   # ...\girlfriend\cowgirl-calendar
$girlDir   = Split-Path -Parent $here                          # ...\girlfriend

if (-not $CalendarPath) { $CalendarPath = Join-Path $here "calendar.txt" }
$StatePath = Join-Path $here "state.json"
$LogPath   = Join-Path $here "cowgirl.log"

function Write-Log([string]$Msg) {
  $line = "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Msg
  try { Add-Content -Path $LogPath -Value $line -Encoding UTF8 } catch {}
  Write-Output $line
}

# --- Telegram: токен/чат из собственного config.json либо из навыков Подружки ---
# (календарь живёт в том же репозитории, что и навыки — дублировать секреты незачем)
if (-not $ConfigPath) { $ConfigPath = Join-Path $here "config.json" }
$candidates = @(
  $ConfigPath,
  (Join-Path $girlDir "skills\heating-telegram\config.json"),
  (Join-Path $girlDir "skills\kotel-guard\config.json")
)
$Token = ""; $ChatId = ""; $cfgUsed = ""
foreach ($c in $candidates) {
  if (-not (Test-Path $c)) { continue }
  try {
    $cfg = Get-Content $c -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.token -and $cfg.chat_id) { $Token = [string]$cfg.token; $ChatId = [string]$cfg.chat_id; $cfgUsed = $c; break }
  } catch {}
}
if (-not $Token) {
  Write-Log "Ошибка: не найден config.json с token/chat_id (см. README → Секреты)."
  exit 2
}

# --- календарь ---
if (-not (Test-Path $CalendarPath)) {
  Write-Log "Ошибка: не найден календарь $CalendarPath"
  exit 2
}

$md = "{0:MM-dd}" -f (Get-Date)          # сегодня в формате месяц-день
$entries = @()
$lineNo = 0
foreach ($raw in [System.IO.File]::ReadAllLines($CalendarPath, [Text.UTF8Encoding]::new($false))) {
  $lineNo++
  $line = $raw.Trim()
  if (-not $line -or $line.StartsWith("#")) { continue }
  $parts = $line -split ";", 2
  if ($parts.Count -ne 2) { Write-Log "Предупреждение: строка $lineNo пропущена (нет ';' ): $line"; continue }
  $period = $parts[0].Trim(); $text = $parts[1].Trim()
  $range = $period -split "\.\.", 2
  $start = $range[0].Trim()
  if ($start -notmatch '^\d{2}-\d{2}$') { Write-Log "Предупреждение: строка $lineNo: дата '$start' не похожа на ММ-ДД"; continue }
  $end = $start
  if ($range.Count -eq 2) {
    $end = $range[1].Trim()
    if ($end -notmatch '^\d{2}-\d{2}$') { Write-Log "Предупреждение: строка $lineNo: дата '$end' не похожа на ММ-ДД"; $end = $start }
  }
  $inPeriod = if ($start -le $end) { $md -ge $start -and $md -le $end } else { $md -ge $start -or $md -le $end }
  $entries += [pscustomobject]@{ Start = $start; End = $end; Text = $text; InPeriod = $inPeriod; Key = "$start|$text" }
}

$due = @($entries | Where-Object { $_.InPeriod })
if ($due.Count -eq 0) {
  Write-Log "Сегодня ($md) сезонных работ нет."
  exit 0
}

# --- состояние: не напоминать об одной работе дважды в год ---
$state = @{ sent = @{} }
if (Test-Path $StatePath) {
  try {
    $s = Get-Content $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $year = [string](Get-Date).Year
    if ($s.sent -and $s.sent.$year) { $state.sent = @{}; foreach ($k in $s.sent.$year) { $state.sent[$k] = $true } }
  } catch { Write-Log "Предупреждение: state.json повреждён, начинаю с чистого листа." }
}

$new = @($due | Where-Object { -not $state.sent.ContainsKey($_.Key) })
if ($new.Count -eq 0) {
  Write-Log "Все работы сезона уже напомнились ($(@($due).Count) активных)."
  exit 0
}

# --- сообщение ---
$stamp = Get-Date -Format "dd.MM.yyyy HH:mm"
$lines = $new | ForEach-Object { "• " + $_.Text + " (до " + $_.End + ")" }
$msg = "<b>🌾 Ковбойша напоминает</b> ($stamp)`n" + ($lines -join "`n")

if ($DryRun -or $Force) {
  Write-Output "DRYRUN: уведомление НЕ отправлено и состояние НЕ изменено. (config: $cfgUsed)"
  Write-Output $msg
  exit 0
}

# --- отправка в Telegram ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$uri = "https://api.telegram.org/bot$Token/sendMessage"
$body = "chat_id=" + [uri]::EscapeDataString($ChatId) +
        "&parse_mode=HTML&disable_web_page_preview=true&text=" + [uri]::EscapeDataString($msg)
try {
  $resp = Invoke-RestMethod -Method Post -Uri $uri -Body $body `
            -ContentType "application/x-www-form-urlencoded; charset=utf-8" -TimeoutSec 30
} catch {
  Write-Log "Ошибка отправки в Telegram: $($_.Exception.Message) — напоминание уйдёт завтра."
  exit 3
}
if (-not $resp.ok) {
  Write-Log "Ошибка отправки в Telegram: $($resp.description)"
  exit 3
}

# --- запоминаем, что напомнили ---
$year = (Get-Date).Year
$allSent = @($due | ForEach-Object { $_.Key })
$out = @{ sent = @{} }   # год -> список ключей (заодно чистим прошлые годы)
$out.sent["$year"] = $allSent
try { ($out | ConvertTo-Json -Depth 4) | Set-Content -Path $StatePath -Encoding UTF8 } catch {}
Write-Log "Отправлено: $($new.Count) напоминание(й): $(($new | ForEach-Object { $_.Text }) -join '; ')"
exit 0
