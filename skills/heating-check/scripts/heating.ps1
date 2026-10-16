# scripts/heating.ps1
# Мониторинг датчиков: значения за последние N минут + статистика.
# По умолчанию — "Отопление" (температура ТЕПЛОНОСИТЕЛЯ, не путать с "котельная").
param(
  [string]$Server = "192.168.88.171:90",
  [string]$Device = "",
  [string]$Preset = "",
  [string]$Column = "",
  [int]$Minutes = 5,
  [int]$Points = 0,   # 0 = авто: число точек (gsCoef) подбирается по глубине окна
  [switch]$List
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}
$base = "http://$Server"

# Быстрые алиасы: имя -> устройство + колонка (+ что именно измеряет)
$presets = @{
  "отопление"         = @{ sname = "Отопление";        col = "cels";  desc = "температура ТЕПЛОНОСИТЕЛЯ" }
  "котельная"         = @{ sname = "котельная";        col = "cels";  desc = "температура воздуха в котельной" }
  "прихожая"          = @{ sname = "прихожая";         col = "cels";  desc = "температура в прихожей" }
  "кухня"             = @{ sname = "кухня";            col = "cels";  desc = "температура на кухне" }
  "ванная"            = @{ sname = "ванная";           col = "cels";  desc = "температура в ванной" }
  "бойлер"            = @{ sname = "Бойлер";           col = "power"; desc = "мощность бойлера" }
  "колодец"           = @{ sname = "Колодец";          col = "power"; desc = "насос/колодец" }
  "вольтметр"         = @{ sname = "Вольтметр";        col = "val";   desc = "напряжение" }
  "большойвольтметр"  = @{ sname = "БольшойВольтметр"; col = "val";   desc = "напряжение" }
  "большой вольтметр" = @{ sname = "БольшойВольтметр"; col = "val";   desc = "напряжение" }
}

$units = @{ cels = "°C"; hum = "%"; batt = "V"; power = "Вт"; epower = "кВт·ч"; val = "" }

# gsCoef — сколько точек возвращает сервер (нормализация ряда), back — глубина окна.
# Правило: с ростом глубины окна поднимаем и число точек, но без десятков тысяч.
#   30 мин -> 30 точек;  1 ч -> 60;  4 ч -> 120;  6 ч -> 240;
#   1 сутки -> 600;  2 суток -> 1000;  неделя -> 2000.
function Get-GsCoef([int]$Minutes) {
  $bounds = @(
    @(30,    30),
    @(60,    60),
    @(240,  120),
    @(360,  240),
    @(1440, 600),
    @(2880, 1000),
    @(10080, 2000)
  )
  $points = 30
  foreach ($b in $bounds) {
    if ($Minutes -ge $b[0]) { $points = $b[1] } else { break }
  }
  return $points
}

try {
  $devs = Invoke-RestMethod -Uri "$base/getdevs" -TimeoutSec 20
} catch {
  Write-Output "Не удалось получить список устройств с $base/getdevs : $($_.Exception.Message)"
  exit 1
}

if ($List) {
  Write-Output "Доступные устройства:"
  $devs | ForEach-Object { Write-Output ("  {0} (gr={1}, cols={2})" -f $_.sname, $_.i, (($_.dots.cols) -join ",")) }
  Write-Output ""
  Write-Output "Быстрые алиасы (параметр -Preset):"
  $presets.Keys | Sort-Object | ForEach-Object {
    Write-Output ("  {0,-18} -> {1} / {2}  ({3})" -f $_, $presets[$_].sname, $presets[$_].col, $presets[$_].desc)
  }
  exit 0
}

$desc = ""
if ($Preset) {
  $key = $Preset.Trim().ToLower()
  if (-not $presets.ContainsKey($key)) {
    Write-Output "Неизвестный алиас '$Preset'. Доступные: $((($presets.Keys | Sort-Object) -join ', '))"
    exit 1
  }
  $Device = $presets[$key].sname
  if (-not $Column) { $Column = $presets[$key].col }
  $desc = $presets[$key].desc
}

if (-not $Device) { $Device = "Отопление" }  # значение по умолчанию

$dev = $devs | Where-Object { $_.sname -like "*$Device*" } | Select-Object -First 1
if (-not $dev) {
  Write-Output "Устройство '$Device' не найдено. Запустите с -List, чтобы увидеть список."
  exit 1
}

if (-not $Column) { $Column = $dev.defcol }
$unit = if ($units.ContainsKey($Column)) { $units[$Column] } else { "" }
$points = if ($Points -gt 0) { $Points } else { Get-GsCoef -Minutes $Minutes }
$url = "$base/getdots?gr=$($dev.i)&col=$Column&back=$Minutes&gsCoef=$points"

try {
  $dots = Invoke-RestMethod -Uri $url -TimeoutSec 20
} catch {
  Write-Output "Ошибка запроса данных: $($_.Exception.Message)"
  exit 1
}

if ($null -eq $dots -or @($dots).Count -eq 0) {
  Write-Output "Нет данных за $Minutes мин ($url)"
  exit 0
}

$inv = [Globalization.CultureInfo]::InvariantCulture
$parsed = @($dots | ForEach-Object {
  $raw = $_.ts
  if ($raw -is [datetime]) {
    $dt = $raw.ToUniversalTime()
  } else {
    $dt = [datetime]::Parse([string]$raw, $inv, [Globalization.DateTimeStyles]::AdjustToUniversal)
  }
  [pscustomobject]@{
    # время как его отдаёт устройство (ts помечен Z, показываем без пересчёта пояса)
    TsStr = $dt.ToString("HH:mm:ss")
    Ts    = $dt
    Val   = [double]$_.val
  }
} | Sort-Object Ts)

$last = $parsed[-1]
$first = $parsed[0]

$title = "Устройство: {0} (gr={1}, col={2}{3})" -f $dev.sname, $dev.i, $Column, $(if ($desc) { " — $desc" } else { "" })
Write-Output $title
Write-Output ("Точек: {0}, окно: ~{1} мин, источник: {2}" -f $parsed.Count, $Minutes, $url)
Write-Output ""

if ($parsed.Count -le 60) {
  foreach ($p in $parsed) {
    $mins = [math]::Round(($last.Ts - $p.Ts).TotalMinutes, 1)
    $label = if ($mins -le 0) { "последнее" } else { "(-$mins мин)" }
    Write-Output ("  {0}  {1,9} {2}   {3}" -f $p.TsStr, $p.Val, $unit, $label)
  }
} else {
  $step = [math]::Round(($last.Ts - $first.Ts).TotalMinutes / ($parsed.Count - 1), 1)
  Write-Output ("  Точка ~каждые {0} мин, всего {1}; ниже первые/последние 3 и сводка." -f $step, $parsed.Count)
  $parsed | Select-Object -First 3 | ForEach-Object { Write-Output ("  {0}  {1,9} {2}" -f $_.TsStr, $_.Val, $unit) }
  Write-Output "  ..."
  $parsed | Select-Object -Last 3 | ForEach-Object { Write-Output ("  {0}  {1,9} {2}" -f $_.TsStr, $_.Val, $unit) }
  Write-Output ""
  Write-Output "  Сводка по промежуткам:"
  $nb = 12
  $bSize = ($last.Ts - $first.Ts).TotalMinutes / $nb
  for ($b = 0; $b -lt $nb; $b++) {
    $tStart = $first.Ts.AddMinutes($b * $bSize)
    $tEnd = $first.Ts.AddMinutes(($b + 1) * $bSize)
    $g = @($parsed | Where-Object { $_.Ts -ge $tStart -and $_.Ts -le $tEnd })
    if ($g.Count -eq 0) { continue }
    $gmin = ($g.Val | Measure-Object -Minimum).Minimum
    $gmax = ($g.Val | Measure-Object -Maximum).Maximum
    $gavg = [math]::Round(($g.Val | Measure-Object -Average).Average, 2)
    Write-Output ("  {0:dd.MM} {0:HH:mm}-{1:HH:mm}  мин={2}{4} макс={3}{4} ср={5}{4}" -f $tStart, $tEnd, $gmin, $gmax, $unit, $gavg)
  }
}

$vals = $parsed | ForEach-Object { $_.Val }
$min = ($vals | Measure-Object -Minimum).Minimum
$max = ($vals | Measure-Object -Maximum).Maximum
$delta = [math]::Round($last.Val - $first.Val, 2)
$span = [math]::Round(($last.Ts - $first.Ts).TotalMinutes, 1)

Write-Output ""
Write-Output ("Мин: {0}{1} | Макс: {2}{3} | Сейчас: {4}{5} | Изменение: {6} за ~{7} мин" -f $min, $unit, $max, $unit, $last.Val, $unit, $delta, $span)
