p=r'D:\_d\u-girlfriend\skills\ups-compress\scripts\ups_compress.py'
s=open(p,encoding='utf-8').read()
old = "         {(f\"(array_agg({qident(c_batt)}) ORDER BY {qident(c_time)}) FILTER (WHERE rn = MAX(rn) OVER (PARTITION BY {qident(c_host) if c_host else \"'x'\"}, {qident(c_model) if c_model else \"'x'\"}, grp)))[1]\" if c_batt else 'NULL')} AS batt_end,"
new = "         {(f\"(array_agg({qident(c_batt)}) ORDER BY {qident(c_time)}) FILTER (WHERE rn = MAX(rn) OVER (PARTITION BY {qident(c_host) if c_host else \"'x'\"}, {qident(c_model) if c_model else \"'x'\"}, grp)))[1]\" if c_batt else \"NULL\")} AS batt_end,"
if old not in s:
    print('no')
    raise SystemExit(1)
s=s.replace(old,new)
open(p,'w',encoding='utf-8').write(s)
print('ok')
