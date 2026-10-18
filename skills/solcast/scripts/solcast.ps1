# scripts/solcast.ps1
# Сколько солнечная панель даст батарее (кВт·ч) сегодня, завтра и дальше.
# Данные берём с сервера voltage: /solcast_data -> таблица dev.solcast.
# В Solcast API НЕ ходим вообще — у бесплатного плана 10 запросов в сутки,
# их тратит crons.js (2 загрузки в сутки: прогноз на 14 дней + факт за 7 дней).
# Параметры:
#   -Days N     сколько дней показывать, начиная с сегодняшнего (по умолчанию 2: сегодня+завтра)
#   -History    история «прогноз против факта» за прошлые дни
#   -Reload     сначала дотянуть свежий прогноз из Solcast (1-2 запроса к API)
param(
  [int]$Days = 2,
  [switch]$History,
  [switch]$Reload
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}

$cfg = Get-Content (Join-Path (Split-Path $PSScriptRoot -Parent) "config.json") -Raw | ConvertFrom-Json
$base = "http://" + $cfg.server

$Months = @{ "01"="января"; "02"="февраля"; "03"="марта"; "04"="апреля"; "05"="мая"; "06"="июня"
             "07"="июля"; "08"="августа"; "09"="сентября"; "10"="октября"; "11"="ноября"; "12"="декабря" }

function Num([double]$n) {
  $n.ToString("0.0", [Globalization.CultureInfo]::GetCultureInfo("ru-RU"))
}
function Ru-Kwh([double]$n) {
  # дробное число — всегда «-часа» (2,5 киловатт-часа); целое — по правилам
  if (([math]::Abs($n) - [math]::Floor([math]::Abs($n))) -gt 0.001) { return "киловатт-часа" }
  $i = [math]::Floor([math]::Abs($n)); $d = $i % 10; $dd = $i % 100
  if ($d -eq 1 -and $dd -ne 11) { return "киловатт-час" }
  if ($d -ge 2 -and $d -le 4 -and ($dd -lt 12 -or $dd -gt 14)) { return "киловатт-часа" }
  return "киловатт-часов"
}
function Ru-Kw([double]$n) {
  if (([math]::Abs($n) - [math]::Floor([math]::Abs($n))) -gt 0.001) { return "киловатта" }
  $i = [math]::Floor([math]::Abs($n)); $d = $i % 10; $dd = $i % 100
  if ($d -eq 1 -and $dd -ne 11) { return "киловатт" }
  if ($d -ge 2 -and $d -le 4 -and ($dd -lt 12 -or $dd -gt 14)) { return "киловатта" }
  return "киловатт"
}

if ($Reload) {
  try { Invoke-RestMethod -Uri "$base/solcast_load" -TimeoutSec 120 | Out-Null }
  catch { "Обновить из Solcast не удалось: " + $_.Exception.Message; exit 1 }
}

try {
  $data = Invoke-RestMethod -Uri "$base/solcast_data" -TimeoutSec 30
} catch {
  "Не удалось получить прогноз солнца: " + $_.Exception.Message
  exit 1
}

if ($History) {
  $h = @($data.history | Where-Object { $null -ne $_.kwh_forecast })
  if ($h.Count -eq 0) {
    "Истории пока нет: прогноз начали собирать недавно, через пару дней будут сравнения."
    exit 0
  }
  $out = foreach ($r in $h) {
    $p = $r.day.Split('-')
    "{0} {1}: обещали {2} {3}, вышло {4}" -f ([int]$p[2]), $Months[$p[1]], (Num $r.kwh_forecast), (Ru-Kwh $r.kwh_forecast), (Num $r.kwh_fact)
  }
  "История точности прогноза. " + ($out -join ". ")
  exit 0
}

$list = @($data.days)   # не $days: перезаписал бы параметр -Days (регистронезависимо)
if ($list.Count -eq 0) {
  "Прогноза пока нет: база пуста, скажите навык солнце обновить, либо подождите утренней загрузки."
  exit 0
}

$today = (Get-Date).ToString("yyyy-MM-dd")
$tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")

$out = foreach ($r in ($list | Select-Object -First $Days)) {
  $p = $r.day.Split('-')
  if ($r.day -eq $today) { $label = "Сегодня" }
  elseif ($r.day -eq $tomorrow) { $label = "Завтра" }
  else { $label = "{0} {1}" -f ([int]$p[2]), $Months[$p[1]] }
  $line = "{0}, {1}: около {2} {3}" -f $label, $r.dow, (Num $r.kwh), (Ru-Kwh $r.kwh)
  if ($r.peak_kw -gt 0.05) {
    $line += ", пик {0} {1} в {2}" -f (Num $r.peak_kw), (Ru-Kw $r.peak_kw), $r.peak_at
  }
  $line
}
($out -join ". ") + "."
