# scripts/plan.ps1
# План на день — файл <корень репозитория>\plan.txt (навык лежит в skills\plan-day\scripts),
# простая форма:
#   [ ] задача    (не сделано)
#   [x] задача    (сделано)
# Можно править руками в блокноте; подружка тоже умеет добавлять и помечать.
#
# Параметры:
#   -Add "текст"    добавить задачу
#   -Done "текст"   отметить сделанной (по части названия, ищем среди [ ])
#   -DoneN N        отметить сделанной (по номеру из -List)
#   -List           показать план с номерами (для голоса)
#   -Clear          убрать строки со сделанными
param(
  [string]$Add = "",
  [string]$Done = "",
  [int]$DoneN = -1,
  [switch]$List,
  [switch]$Clear
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}
# путь к plan.txt — три уровня вверх: scripts → plan-day → skills → корень репозитория
$planPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\..\plan.txt"))
$utf8 = New-Object System.Text.UTF8Encoding $false

function Read-PlanFile {
  if (-not (Test-Path $planPath)) { return @() }
  return @([System.IO.File]::ReadAllLines($planPath, $utf8))
}

if (-not (Test-Path $planPath)) {
  $head = @(
    "# План на день",
    "# [ ] - задача, [x] - сделано. Правь руками или голосом: подружка, навык план ..."
  )
  [System.IO.File]::WriteAllLines($planPath, $head, $utf8)
}

$lines = Read-PlanFile

if ($Add -ne "") {
  $text = $Add.Trim()
  $lines += "[ ] " + $text
  [System.IO.File]::WriteAllLines($planPath, $lines, $utf8)
  "Добавлено в план: " + $text
  exit 0
}

if ($DoneN -gt 0) {
  $n = 0
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\[ \] ') {
      $n++
      if ($n -eq $DoneN) {
        $task = $lines[$i] -replace '^\[ \] ', ''
        $lines[$i] = "[x] " + $task
        [System.IO.File]::WriteAllLines($planPath, $lines, $utf8)
        "Отметил сделанным: " + $task
        exit 0
      }
    }
  }
  "Не нашёл задачи с номером " + $DoneN
  exit 1
}

if ($Done -ne "") {
  $needle = $Done.Trim().ToLower()
  foreach ($line in $lines) {
    if ($line -match '^\[ \] ' -and $line.ToLower().Contains($needle)) {
      $task = $line -replace '^\[ \] ', ''
      for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -eq $line) { $lines[$i] = "[x] " + $task; break }
      }
      [System.IO.File]::WriteAllLines($planPath, $lines, $utf8)
      "Отметил сделанным: " + $task
      exit 0
    }
  }
  "В плане не вижу: " + $Done.Trim()
  exit 1
}

if ($Clear) {
  $kept = @($lines | Where-Object { $_ -notmatch '^\[x\] ' })
  [System.IO.File]::WriteAllLines($planPath, $kept, $utf8)
  "Убрал сделанные задачи"
  exit 0
}

# Показать план (по умолчанию и при -List)
$todoCount = 0; $doneCount = 0
foreach ($line in $lines) {
  if ($line -match '^\[ \] ') { $todoCount++ }
  elseif ($line -match '^\[x\] ') { $doneCount++ }
}
$out = @()
$out += "План на день: в работе " + $todoCount + ", сделано " + $doneCount + "."
$n = 0
foreach ($line in $lines) {
  if ($line -match '^\[ \] ') {
    $n++
    $out += ($n.ToString() + ". " + ($line -replace '^\[ \] ', ''))
  } elseif ($line -match '^\[x\] ') {
    $out += (($line -replace '^\[x\] ', '') + " - сделано")
  }
}
$out -join [Environment]::NewLine
exit 0