# scripts/weather.ps1
# Погода в Турмантасе (gismeteo.ru/weather-turmantas-16326).
# По умолчанию: сейчас + сегодня (по часам) + завтра.
# Параметры:
#   -Now   только "сейчас"
#   -Ten   прогноз на 10 дней (кратко по дням)
param(
  [switch]$Ten,
  [switch]$Now
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Base = "https://www.gismeteo.ru/weather-turmantas-16326"

$wdN = @{
  "вс" = "воскресенье"; "пн" = "понедельник"; "вт" = "вторник"; "ср" = "среда"
  "чт" = "четверг";     "пт" = "пятница";     "сб" = "суббота"
}

function Get-Page($url) {
  $r = Invoke-WebRequest -Uri $url -UseBasicParsing -UserAgent (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
  ) -Headers @{ "Accept-Encoding" = "identity"; "Accept-Language" = "ru" } -TimeoutSec 30
  return $r.Content
}

function Get-TabDesc($tabHtml) {
  $m = [regex]::Match($tabHtml, 'data-tooltip="([^"]+)"')
  if ($m.Success) { return $m.Groups[1].Value }
  return ""
}

function Get-TabTemps($tabHtml) {
  $vals = @()
  foreach ($m in [regex]::Matches($tabHtml, 'value="(-?\d+)"')) {
    $vals += [int]$m.Groups[1].Value
  }
  return ,$vals
}

function Format-Desc($d) {
  if (-not $d -or $d.Length -lt 2) { return $d }
  return $d.Substring(0, 1).ToUpper() + $d.Substring(1)
}

function Get-HourlySummary($todayHtml) {
  # блок с почасовкой на сегодня (3-часовые интервалы)
  $h3 = [regex]::Match($todayHtml, '(?s)class="widget widget--h3[^"]*"[\s\S]*?</section>').Value
  if (-not $h3) { return "по часам не получилось" }
  $times = [regex]::Matches($h3, 'class="row-item-time"\s*timestamp="(\d+)"')
  $icons = [regex]::Matches($h3, '<div class="row-item" data-tooltip="([^"]+)"')
  if ($times.Count -eq 0 -or $times.Count -ne $icons.Count) {
    return "по часам не получилось"
  }
  $hours = @()
  for ($i = 0; $i -lt $times.Count; $i++) {
    $dt = [DateTimeOffset]::FromUnixTimeSeconds([int64]$times[$i].Groups[1].Value).ToLocalTime()
    $hours += $dt.ToString("HH:mm")
  }
  # объединяем подряд одинаковые описания в диапазоны
  $ranges = @()
  $gStart = ""; $gDesc = ""
  for ($i = 0; $i -lt $icons.Count; $i++) {
    $d = $icons[$i].Groups[1].Value
    if ($d -ne $gDesc) {
      if ($gDesc -ne "") { $ranges += @{ s = $gStart; e = $hours[$i-1]; d = $gDesc } }
      $gStart = $hours[$i]; $gDesc = $d
    }
  }
  if ($gDesc -ne "") { $ranges += @{ s = $gStart; e = $hours[$hours.Count-1]; d = $gDesc } }
  $parts = foreach ($rg in $ranges) {
    if ($rg.s -eq $rg.e) { "$($rg.s): $($rg.d)" }
    else { "с $($rg.s) до $($rg.e): $($rg.d)" }
  }
  return ($parts -join "; ")
}

try {
  if ($Ten) {
    $d10 = Get-Page "$Base/10-days/"
    $hdr = @([regex]::Matches($d10, '<div class="day">([^<]+)</div>\s*<div class="date">([^<]+)</div>'))
    $icn = @([regex]::Matches($d10, '<div class="row-item" data-tooltip="([^"]+)"'))
    if ($hdr.Count -lt 10 -or $icn.Count -lt 10) {
      "Не смогла разобрать прогноз на 10 дней (временный сбой Gismeteo?)."
    } else {
      $lines = @()
      for ($i = 0; $i -lt 10; $i++) {
        $wd = $hdr[$i].Groups[1].Value
        $dt = $hdr[$i].Groups[2].Value
        $name = $wdN[$wd]; if (-not $name) { $name = $wd }
        $lines += "$name ${dt}: $($icn[$i].Groups[1].Value)"
      }
      "На 10 дней: " + ($lines -join "; ")
    }
    exit 0
  }

  $today = Get-Page "$Base/"
  $anchorTabs = [regex]::Matches($today, '(?s)<a class="weathertab"[\s\S]*?</a>')
  $nowTab = $null; $tomTab = $null
  foreach ($t in $anchorTabs) {
    if ($t.Value -match 'Сейчас') { $nowTab = $t.Value }
    elseif ($t.Value -match 'Завтра') { $tomTab = $t.Value }
  }
  $dayTab = [regex]::Match($today, '(?s)<div class="weathertab is-active[^>]*>[\s\S]*?(?=<a class="weathertab)').Value
  if (-not $dayTab) { $dayTab = $null }

  if (-not $nowTab) { throw "Вкладка 'Сейчас' не найдена на странице" }

  $nowT = Get-TabTemps $nowTab
  $nowLine = "Сейчас " + $nowT[0] + " градусов"
  if ($nowT.Count -gt 1) { $nowLine += ", ощущается " + $nowT[1] }
  $nowLine += ". " + (Format-Desc (Get-TabDesc $nowTab)) + "."
  if ($Now) { $nowLine; exit 0 }

  $out = @($nowLine)

  if ($dayTab) {
    $dt = Get-TabTemps $dayTab
    $dayLine = "Сегодня: " + (Format-Desc (Get-TabDesc $dayTab))
    if ($dt.Count -ge 2) { $dayLine += ", " + $dt[0] + ".." + $dt[1] + " градусов" }
    $dayLine += ". По часам: " + (Get-HourlySummary $today) + "."
    $out += $dayLine
  }

  if ($tomTab) {
    $tt = Get-TabTemps $tomTab
    $tomLine = "Завтра: " + (Format-Desc (Get-TabDesc $tomTab))
    if ($tt.Count -ge 2) { $tomLine += ", " + $tt[0] + ".." + $tt[1] + " градусов" }
    $out += ($tomLine + ".")
  }

  $out -join [Environment]::NewLine
  exit 0
}
catch {
  "Не удалось получить погоду: " + $_.Exception.Message
  exit 1
}