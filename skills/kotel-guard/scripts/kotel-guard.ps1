# scripts/kotel-guard.ps1
# kotel-guard — фоновый наблюдатель за отоплением.
# Каждые N минут (Планировщик задач) сверяет текущую температуру теплоносителя
# с минимумом за окно. Если подъём >= порога (котёл разожжён) — шлёт
# уведомление в Telegram: проверить заслонку и насос. Одно уведомление
# на одну топку: повторно шлёт только после остывания (перерезагорание).
#
# Запуск вручную:
#   powershell -File kotel-guard.ps1            # обычный цикл проверки
#   powershell -File kotel-guard.ps1 -DryRun    # показать решение, ничего не слать/менять
#   powershell -File kotel-guard.ps1 -Force     # отправить тестовое уведомление сразу
param(
  [switch]$DryRun,   # проверить и распечатать решение, без отправки и без изменения состояния
  [switch]$Force,    # послать уведомление немедленно, игнорируя порог и состояние
  [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path   # ...\skills\kotel-guard\scripts
$skillDir = Split-Path -Parent $here                      # ...\skills\kotel-guard

if (-not $ConfigPath) { $ConfigPath = Join-Path $skillDir "config.json" }
$StatePath = Join-Path $skillDir "state.json"
$LogPath   = Join-Path $skillDir "kotel-guard.log"

function Write-Log([string]$Msg) {
  $line = "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Msg
  try { Add-Content -Path $LogPath -Value $line -Encoding UTF8 } catch {}
  Write-Output $line
}

# --- конфиг ---
if (-not (Test-Path $ConfigPath)) {
  Write-Log "Ошибка: не найден конфиг $ConfigPath"
  exit 2
}
try {
  $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
  Write-Log "Ошибка: не удалось прочитать конфиг $ConfigPath : $($_.Exception.Message)"
  exit 2
}

$Server   = if ($cfg.server)          { [string]$cfg.server }          else { "192.168.88.171:90" }
$Token    = [string]$cfg.token
$ChatId   = [string]$cfg.chat_id
$Device   = if ($cfg.device)          { [string]$cfg.device }          else { "Отопление" }
$Column   = if ($cfg.column)          { [string]$cfg.column }          else { "cels" }
$Threshold = if ($cfg.threshold_c)     { [double]$cfg.threshold_c }     else { 20 }
$Window    = if ($cfg.window_minutes)  { [int]$cfg.window_minutes }     else { 180 }
$Rearm     = if ($cfg.rearm_ratio)     { [double]$cfg.rearm_ratio }     else { 0.5 }
$Unit = "°C"

if (-not $Token)  { Write-Log "Ошибка: не задан токен бота (config.json → token).";  exit 2 }
if (-not $ChatId) { Write-Log "Ошибка: не задан chat_id (config.json → chat_id)."; exit 2 }

# --- состояние (одно уведомление на одну топку) ---
$state = [ordered]@{ armed = $true; last_ts = ""; last_notified = ""; last_delta = 0 }
if (Test-Path $StatePath) {
  try {
    $s = Get-Content $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $state.armed         = [bool]$s.armed
    $state.last_ts       = [string]$s.last_ts
    $state.last_notified = [string]$s.last_notified
    $state.last_delta    = [double]$s.last_delta
  } catch {
    Write-Log "Предупреждение: state.json повреждён, использую значения по умолчанию."
  }
}

function Save-State {
  if ($DryRun) { return }
  try {
    ($state | ConvertTo-Json) | Set-Content -Path $StatePath -Encoding UTF8
  } catch { Write-Log "Предупреждение: не удалось сохранить state.json: $($_.Exception.Message)" }
}

# --- данные мониторинга (те же эндпоинты, что у graph.html) ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$base = "http://$Server"
try {
  $devs = Invoke-RestMethod -Uri "$base/getdevs" -TimeoutSec 20
} catch {
  Write-Log "Ошибка: нет связи с $base/getdevs : $($_.Exception.Message)"
  exit 3
}
$dev = $devs | Where-Object { $_.sname -like "*$Device*" } | Select-Object -First 1
if (-not $dev) { Write-Log "Ошибка: устройство '$Device' не найдено в /getdevs."; exit 3 }
if (-not $Column) { $Column = $dev.defcol }

# число точек: по глубине окна (та же логика, что в heating.ps1)
$points = 30
foreach ($b in @(@(30,30), @(60,60), @(240,120), @(360,240), @(1440,600))) {
  if ($Window -ge $b[0]) { $points = $b[1] } else { break }
}
$url = "$base/getdots?gr=$($dev.i)&col=$Column&back=$Window&gsCoef=$points"
try {
  $dots = Invoke-RestMethod -Uri $url -TimeoutSec 20
} catch {
  Write-Log "Ошибка: нет данных с $url : $($_.Exception.Message)"
  exit 3
}
if ($null -eq $dots -or @($dots).Count -eq 0) {
  Write-Log "Нет точек за $Window мин ($url) — пропускаю."
  exit 3
}

$inv = [Globalization.CultureInfo]::InvariantCulture
$parsed = @($dots | ForEach-Object {
  $dt = [datetime]::Parse([string]$_.ts, $inv, [Globalization.DateTimeStyles]::AdjustToUniversal)
  [pscustomobject]@{ TsStr = [string]$_.ts; Ts = $dt; Val = [double]$_.val }
} | Sort-Object Ts)

$last  = $parsed[-1]
$vals  = $parsed | ForEach-Object { $_.Val }
$min   = ($vals | Measure-Object -Minimum).Minimum
$current = $last.Val
$delta = [math]::Round($current - $min, 1)
$RearmLevel = $Threshold * $Rearm

# --- данные не обновились? (ts не сдвинулся с прошлой проверки) ---
# сравниваем ts последней точки с сохранённым: без привязки к локальным часам,
# поэтому расхождение пояса устройства не влияет.
if (-not $Force -and $state.last_ts -and $state.last_ts -eq $last.TsStr) {
  Write-Log "Новых данных нет (последняя точка $current$Unit не изменилась) — пропускаю."
  exit 4
}

# --- решение ---
$decision = ""
if ($Force -or ($state.armed -and $delta -ge $Threshold)) {
  $decision = "fire"
} elseif (-not $state.armed -and $delta -le $RearmLevel) {
  $decision = "rearm"
} else {
  $decision = "none"
}

Write-Log ("Проверка: {0} ({1}{2}), мин за {3} мин = {4}{2}, подъём = {5}{2}, состояние = {6}, решение = {7}" -f `
  $Device, $current, $Unit, $Window, $min, $delta, $(if ($state.armed) { "вооружено" } else { "уже уведомлено" }), $decision)

if ($decision -eq "rearm") {
  $state.armed = $true
  Save-State
  exit 0
}
if ($decision -ne "fire") {
  $state.last_ts = $last.TsStr
  $state.last_delta = $delta
  Save-State
  exit 0
}

# --- формируем уведомление ---
$stamp = Get-Date -Format "dd.MM.yyyy HH:mm"
$fireWord = if ($Force) { "🔥 Котёл разожжён (тестовое)" } else { "🔥 Котёл разожжён" }
$msg = "<b>$fireWord</b> ($stamp)`n" +
       "<b>${Device}:</b> $min → $current $Unit (+$delta $Unit за $Window мин)`n" +
       "Проверь, закрыта ли заслонка, и включился ли насос!"

if ($DryRun) {
  Write-Output "DRYRUN: уведомление НЕ отправлено и состояние НЕ изменено."
  Write-Output $msg
  exit 0
}

# --- отправка в Telegram ---
# все вставки в $msg — числа и имена из конфига (без <, >, &), теги <b> оставляем
$uri = "https://api.telegram.org/bot$Token/sendMessage"
$body = "chat_id=" + [uri]::EscapeDataString($ChatId) +
        "&parse_mode=HTML&disable_web_page_preview=true&text=" + [uri]::EscapeDataString($msg)

try {
  $resp = Invoke-RestMethod -Method Post -Uri $uri -Body $body `
            -ContentType "application/x-www-form-urlencoded; charset=utf-8" -TimeoutSec 30
} catch {
  # не считаем топку отслеженной: при ошибке сети уведомление уйдёт в следующий цикл
  Write-Log "Ошибка отправки в Telegram: $($_.Exception.Message)"
  exit 5
}
if (-not $resp.ok) {
  Write-Log "Ошибка отправки в Telegram: $($resp.description)"
  exit 5
}

$state.armed = $false
$state.last_ts = $last.TsStr
$state.last_notified = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
$state.last_delta = $delta
Save-State
Write-Log "Отправлено в Telegram: подъём +$delta$Unit ($min → $current$Unit)."
exit 0
