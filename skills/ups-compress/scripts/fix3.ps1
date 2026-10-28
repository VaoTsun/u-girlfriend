$p = "D:\_d\u-girlfriend\skills\ups-compress\scripts\ups_compress.py"
$s = [System.IO.File]::ReadAllText($p)
$s2 = $s.Replace("'NULL'", '"NULL"')
[System.IO.File]::WriteAllText($p, $s2)
Write-Host "done"
