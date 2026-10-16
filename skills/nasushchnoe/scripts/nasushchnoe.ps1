# scripts/nasushchnoe.ps1
# Насущное — общие дела «когда-нибудь надо».
# Источник правды — база: таблица dev.nasushchnoe (база d на 192.168.88.171).
# Данные идут через endpoint /sql?sql=... (см. SQL_ALLOWLIST в web.server.js).
#
# Адрес сайта: по умолчанию пробуем по очереди боевой http://192.168.88.171:90,
# затем локальный dev http://127.0.0.1:90 (можно переопределить -Api).
# Страница: /nas.html (ссылка «Насущное» в меню).
#
# Параметры:
#   -Add "текст"     добавить дело
#   -Done "текст"    отметить сделанным (по части названия)
#   -DoneN N         отметить сделанным (по номеру из -List)
#   -Remove "текст"  убрать дело (по части названия)
#   -List            показать список с номерами (для голоса)
#   -Clear           убрать все сделанные дела
param(
  [string]$Api = "",
  [string]$Add = "",
  [string]$Done = "",
  [int]$DoneN = -1,
  [string]$Remove = "",
  [switch]$List,
  [switch]$Clear
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}

$apiCandidates = if ($Api -ne "") { @($Api) } else { @("http://192.168.88.171:90", "http://127.0.0.1:90") }
$script:base = $null

function Get-Base {
  if ($script:base) { return $script:base }
  foreach ($a in $apiCandidates) {
    try {
      $null = Invoke-WebRequest -Uri "$a/sql?sql=dev.nasushchnoe.list.sql" -UseBasicParsing -TimeoutSec 5
      $script:base = $a
      return $a
    } catch { }
  }
  throw ("Ни один сайт не отвечает на /sql: " + ($apiCandidates -join ", "))
}

# PS 5.1: ConvertFrom-Json отдаёт JSON-массив одним объектом,
# поэтому раскладываем его foreach'ем в честный массив строк
function Convert-Rows([string]$json) {
  $rows = @()
  foreach ($r in (ConvertFrom-Json $json)) { $rows += $r }
  return $rows
}

function Get-Items {
  $b = Get-Base
  $json = (Invoke-WebRequest -Uri "$b/sql?sql=dev.nasushchnoe.list.sql" -UseBasicParsing -TimeoutSec 10).Content
  return (Convert-Rows $json)
}

function Invoke-Sql([string]$file, [string[]]$vals) {
  $b = Get-Base
  $u = "$b/sql?sql=$file"
  foreach ($v in $vals) { $u += "&vals[]=" + [uri]::EscapeDataString($v) }
  $json = (Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 20).Content
  return (Convert-Rows $json)
}

if ($Add -ne "") {
  $r = Invoke-Sql "dev.nasushchnoe.ins.sql" @($Add.Trim(), "")
  "Добавлено в насущное (#" + $r.i + "): " + $r.title
  exit 0
}

$items = @(Get-Items)

if ($DoneN -gt 0) {
  $open = @($items | Where-Object { -not $_.done })
  if ($DoneN -le $open.Count) {
    $t = $open[$DoneN - 1]
    $r = Invoke-Sql "dev.nasushchnoe.done.sql" @("$($t.i)")
    if ($r.done) { "Отметил сделанным: " + $t.title } else { "Вернул в работу: " + $t.title }
    exit 0
  }
  "Не нашёл дела с номером " + $DoneN
  exit 1
}

if ($Done -ne "") {
  $needle = $Done.Trim().ToLower()
  $t = $items | Where-Object { -not $_.done -and $_.title.ToLower().Contains($needle) } | Select-Object -First 1
  if ($null -ne $t) {
    $r = Invoke-Sql "dev.nasushchnoe.done.sql" @("$($t.i)")
    if ($r.done) { "Отметил сделанным: " + $t.title } else { "Вернул в работу: " + $t.title }
    exit 0
  }
  "В насущном не вижу: " + $Done.Trim()
  exit 1
}

if ($Remove -ne "") {
  $needle = $Remove.Trim().ToLower()
  $t = $items | Where-Object { $_.title.ToLower().Contains($needle) } | Select-Object -First 1
  if ($null -ne $t) {
    $null = Invoke-Sql "dev.nasushchnoe.del.sql" @("$($t.i)")
    "Убрал из насущного: " + $t.title
    exit 0
  }
  "В насущном не вижу: " + $Remove.Trim()
  exit 1
}

if ($Clear) {
  $done = @($items | Where-Object { $_.done })
  foreach ($d in $done) { $null = Invoke-Sql "dev.nasushchnoe.del.sql" @("$($d.i)") }
  "Убрал сделанные дела: " + $done.Count
  exit 0
}

# Показать список (по умолчанию и при -List)
$open = @($items | Where-Object { -not $_.done })
$finished = @($items | Where-Object { $_.done })
$out = @()
$out += "Насущное: в работе " + $open.Count + ", сделано " + $finished.Count + "."
$n = 0
foreach ($it in $open) {
  $n++
  $out += ($n.ToString() + ". " + $it.title)
}
foreach ($it in $finished) {
  $out += ($it.title + " - сделано")
}
$out -join [Environment]::NewLine
exit 0
