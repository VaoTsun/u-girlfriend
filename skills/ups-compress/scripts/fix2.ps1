$p = "D:\_d\u-girlfriend\skills\ups-compress\scripts\ups_compress.py"
$s = Get-Content -Raw $p
$old = '         {(f"(array_agg({qident(c_batt)}) ORDER BY {qident(c_time)}) FILTER (WHERE rn = MAX(rn) OVER (PARTITION BY {qident(c_host) if c_host else "' + "'x'" + '"}, {qident(c_model) if c_model else "' + "'x'" + '"}, grp)))[1]" if c_batt else ' + "'NULL'" + ')} AS batt_end,'
$new = '         {(f"(array_agg({qident(c_batt)}) ORDER BY {qident(c_time)}) FILTER (WHERE rn = MAX(rn) OVER (PARTITION BY {qident(c_host) if c_host else "' + "'x'" + '"}, {qident(c_model) if c_model else "' + "'x'" + '"}, grp)))[1]" if c_batt else "' + '"NULL"' + ')} AS batt_end,'
if ($s -like "*$old*") {
  $s = $s.Replace($old, $new)
  Set-Content -Path $p -Value $s -NoNewline
  Write-Host "ok"
} else {
  Write-Host "no"
}
