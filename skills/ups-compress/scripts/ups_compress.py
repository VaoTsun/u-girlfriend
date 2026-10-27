#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta


def load_env_file(path):
    env = {}
    if not path or not os.path.exists(path):
        return env
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    env[k] = v
    except Exception as e:
        print(f"[WARN] cannot read env {path}: {e}", file=sys.stderr)
    return env


def get_db_env(skill_dir):
    cfg_path = os.path.join(skill_dir, 'config.json')
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[WARN] cannot read config.json: {e}", file=sys.stderr)
    env_path_prod = cfg.get('env_path_prod') or '/home/vao/u-barn/.env'
    env = {}
    for p in [os.path.join(skill_dir, '.env'), env_path_prod]:
        if p and os.path.exists(p):
            env.update(load_env_file(p))
            break
    for k in ['PGHOST','PGPORT','PGUSER','PGPASSWORD','PGDATABASE','DB_PASSWORD','DB_USER','DB_NAME','DB_HOST']:
        if k in os.environ and k not in env:
            env[k] = os.environ[k]
    return env, cfg


def psql(env, sql, psql_bin='psql', dry=False, timeout=600):
    if dry:
        print('[DRY] SQL:\n' + sql)
        return ''
    db = env.get('PGDATABASE') or env.get('DB_NAME') or 'd'
    user = env.get('PGUSER') or env.get('DB_USER') or os.environ.get('USER') or 'app'
    password = env.get('PGPASSWORD') or env.get('DB_PASSWORD') or ''
    pghost = env.get('PGHOST') or env.get('DB_HOST') or ''
    pgport = env.get('PGPORT') or env.get('DB_PORT') or ''

    cmd = [psql_bin]
    if pghost and pghost not in ('127.0.0.1','localhost'):
        cmd += ['-h', pghost]
        if pgport:
            cmd += ['-p', str(pgport)]
    cmd += ['-d', db, '-U', user, '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\t']

    run_env = os.environ.copy()
    if password:
        run_env['PGPASSWORD'] = password
    try:
        proc = subprocess.Popen(cmd + ['-c', sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=run_env)
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError('psql timeout')
    if proc.returncode != 0:
        raise RuntimeError(f'psql failed: {err.decode("utf-8", errors="ignore")}')
    return out.decode('utf-8', errors='ignore')


def qident(s):
    return '"' + s.replace('"','""') + '"'


def get_cols(env, schema, table, psql_bin):
    sql = f"SELECT column_name FROM information_schema.columns WHERE table_schema='{schema}' AND table_name='{table}' ORDER BY ordinal_position;"
    out = psql(env, sql, psql_bin, dry=False)
    cols = []
    for l in out.strip().split('\n'):
        l = l.strip()
        if l:
            cols.append(l)
    return cols


def main():
    ap = argparse.ArgumentParser(description='Compress dev.upsd into events/hourly')
    ap.add_argument('--apply', action='store_true', help='Actually insert/delete')
    ap.add_argument('--dry-run', action='store_true', help='Dry run')
    ap.add_argument('--config', help='Path to config.json')
    args = ap.parse_args()
    dry = not args.apply if not args.dry_run else True
    if args.apply and args.dry_run:
        dry = True

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env, cfg = get_db_env(skill_dir)
    if args.config and os.path.exists(args.config):
        with open(args.config,'r',encoding='utf-8') as f:
            cfg.update(json.load(f))

    schema = cfg.get('schema','dev')
    src = cfg.get('source_table','upsd')
    ev = cfg.get('events_table','upsd_events')
    hr = cfg.get('hourly_table','upsd_hourly')
    keep_days = int(cfg.get('keep_days',14))
    batch_size = int(cfg.get('batch_size',50000))
    win = cfg.get('window_statuses',['OB','DISCHRG','ALARM','LB'])
    norm = cfg.get('normal_statuses',['OL','OL CHRG'])
    psql_bin = cfg.get('psql_bin','psql')

    S = qident(schema)
    ST = qident(src)
    ET = qident(ev)
    HT = qident(hr)
    win_sql = ','.join(["'%s'" % w.replace("'", "''") for w in win])
    norm_sql = ','.join(["'%s'" % n.replace("'", "''") for n in norm])

    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime('%Y-%m-%d %H:%M:%S')
    dbn = env.get('PGDATABASE') or env.get('DB_NAME')
    pgu = env.get('PGUSER') or env.get('DB_USER')
    pgh = env.get('PGHOST') or env.get('DB_HOST') or '(socket)'
    print(f"[INFO] mode={'DRY-RUN' if dry else 'APPLY'} keep_days={keep_days} cutoff<{cutoff}")
    print(f"[INFO] db={dbn}@{pgh} user={pgu}")
    print(f"[INFO] tables: {schema}.{src} -> {schema}.{ev}, {schema}.{hr}")
    print(f"[INFO] window_statuses={win} normal_statuses={norm}")

    cols = get_cols(env, schema, src, psql_bin)
    print(f"[INFO] {src} columns: {', '.join(cols)}")
    c_time = 'time' if 'time' in cols else ('ts' if 'ts' in cols else cols[0])
    c_host = 'host' if 'host' in cols else None
    c_model = 'model' if 'model' in cols else None
    c_status = 'ups_status' if 'ups_status' in cols else ('status' if 'status' in cols else None)
    c_batt = 'battery_charge_percent' if 'battery_charge_percent' in cols else ('batt' if 'batt' in cols else None)
    c_load = 'load_percent' if 'load_percent' in cols else ('ups_load_percent' if 'ups_load_percent' in cols else ('load' if 'load' in cols else None))
    c_in = 'input_voltage' if 'input_voltage' in cols else ('in_voltage' if 'in_voltage' in cols else None)
    c_out = 'output_voltage' if 'output_voltage' in cols else ('out_voltage' if 'out_voltage' in cols else None)
    if not c_status:
        raise RuntimeError('ups_status/status not found')
    print(f"[INFO] using: time={c_time} host={c_host} model={c_model} status={c_status} batt={c_batt} load={c_load} in={c_in} out={c_out}")

    sel = []
    sel.append(qident(c_time))
    if c_host:
        sel.append(qident(c_host))
    if c_model:
        sel.append(qident(c_model))
    sel.append(qident(c_status))
    if c_batt:
        sel.append(qident(c_batt))
    if c_load:
        sel.append(qident(c_load))
    if c_in:
        sel.append(qident(c_in))
    if c_out:
        sel.append(qident(c_out))
    sel_sql = ','.join(sel)

    phost = qident(c_host) if c_host else "'x'"
    pmodel = qident(c_model) if c_model else "'x'"
    phost_u = qident(c_host) if c_host else "'unknown'"
    pmodel_u = qident(c_model) if c_model else "'unknown'"

    batt_start_e = f'MIN({qident(c_batt)})' if c_batt else 'NULL'
    batt_min_e = batt_start_e
    batt_max_e = f'MAX({qident(c_batt)})' if c_batt else 'NULL'
    if c_batt:
        batt_end_e = "(SELECT " + qident(c_batt) + " FROM ordered o2 WHERE o2.grp = ordered.grp AND o2." + qident(c_host if c_host else c_time) + " = ordered." + qident(c_host if c_host else c_time) + " AND o2." + qident(c_model if c_model else c_time) + " = ordered." + qident(c_model if c_model else c_time) + " ORDER BY o2." + qident(c_time) + " DESC LIMIT 1)"
    else:
        batt_end_e = 'NULL'
    load_max_e = f'MAX({qident(c_load)})' if c_load else 'NULL'
    in_min_e = f'MIN({qident(c_in)})' if c_in else 'NULL'
    in_max_e = f'MAX({qident(c_in)})' if c_in else 'NULL'
    out_min_e = f'MIN({qident(c_out)})' if c_out else 'NULL'
    out_max_e = f'MAX({qident(c_out)})' if c_out else 'NULL'

    sql_win = f"""
WITH ordered AS (
  SELECT {sel_sql},
         ROW_NUMBER() OVER (PARTITION BY {phost}, {pmodel} ORDER BY {qident(c_time)}) AS rn,
         ROW_NUMBER() OVER (PARTITION BY {phost}, {pmodel}, CASE WHEN {qident(c_status)} IN ({win_sql}) THEN 1 ELSE 0 END ORDER BY {qident(c_time)}) AS grp
  FROM {S}.{ST}
  WHERE {qident(c_time)} < '{cutoff}'
),
windows AS (
  SELECT {phost_u} AS host, {pmodel_u} AS model,
         MIN({qident(c_time)}) AS started_at, MAX({qident(c_time)}) AS ended_at,
         {batt_start_e} AS batt_start,
         {batt_min_e} AS batt_min,
         {batt_max_e} AS batt_max,
         ({batt_end_e}) AS batt_end,
         {load_max_e} AS load_max,
         {in_min_e} AS in_min,
         {in_max_e} AS in_max,
         {out_min_e} AS out_min,
         {out_max_e} AS out_max,
         COUNT(*) AS cnt,
         ARRAY_AGG({qident(c_status)} ORDER BY {qident(c_time)}) AS statuses
  FROM ordered
  WHERE {qident(c_status)} IN ({win_sql})
  GROUP BY {phost}, {pmodel}, grp
)
SELECT host, model, started_at, ended_at, EXTRACT(EPOCH FROM (ended_at - started_at))::int AS duration_sec,
       batt_start, batt_min, batt_end, load_max, in_min, in_max, out_min, out_max, cnt, statuses
FROM windows
ORDER BY started_at;
"""

    print('[INFO] scanning event windows...')
    out_win = psql(env, sql_win, psql_bin, dry=False)
    lines = [l for l in out_win.strip().split('\n') if l.strip()]
    print(f'[INFO] found {len(lines)} event windows')

    if not dry and lines:
        ins_ev = []
        for l in lines:
            parts = l.split('\t')
            if len(parts) < 15:
                continue
            host, model, started_at, ended_at, duration_sec, batt_start, batt_min, batt_end, load_max, in_min, in_max, out_min, out_max, cnt, statuses = parts[:15]

            def ni(x):
                try:
                    if x == '' or str(x).lower() == 'null':
                        return 'NULL'
                    return x
                except Exception:
                    return 'NULL'

            def ns(x):
                try:
                    if x == '' or str(x).lower() == 'null':
                        return 'NULL'
                    return "'" + str(x).replace("'", "''") + "'"
                except Exception:
                    return 'NULL'

            st0 = statuses.strip('{}').split(',')[0].strip('"').strip() if statuses else ''
            tmap = {'OB': 'on_batt', 'DISCHRG': 'on_batt', 'ALARM': 'alarm', 'LB': 'low_batt'}
            etype = tmap.get(st0, 'other')
            details = json.dumps({'statuses': [s.strip('"') for s in statuses.strip('{}').split(',')] if statuses and statuses != '{}' else []}).replace("'", "''")
            ins_ev.append(f"({ns(host)},{ns(model)},{ns(started_at)},{ns(ended_at)},'{etype}',{ni(batt_start)},{ni(batt_min)},{ni(batt_end)},{ni(load_max)},{ni(in_min)},{ni(in_max)},{ni(out_min)},{ni(out_max)},{ni(duration_sec)},'{details}'::jsonb)")

        for i in range(0, len(ins_ev), batch_size):
            batch = ins_ev[i:i + batch_size]
            sql_ins = f"INSERT INTO {S}.{ET} (host,model,started_at,ended_at,type,batt_start,batt_min,batt_end,load_max,in_min,in_max,out_min,out_max,duration_sec,details) VALUES {','.join(batch)};"
            psql(env, sql_ins, psql_bin, dry=False)
        print(f'[INFO] inserted {len(ins_ev)} events into {schema}.{ev}')

    sql_hr = f"""
WITH base AS (
  SELECT {qident(c_host) if c_host else "'unknown'"} AS host, {qident(c_model) if c_model else "'unknown'"} AS model,
         date_trunc('hour', {qident(c_time)}) AS hour, {qident(c_status)} AS ups_status,
         {qident(c_batt) if c_batt else 'NULL'} AS battery_charge_percent,
         {qident(c_load) if c_load else 'NULL'} AS ups_load_percent,
         {qident(c_in) if c_in else 'NULL'} AS input_voltage,
         {qident(c_out) if c_out else 'NULL'} AS output_voltage,
         {qident(c_time)} AS t
  FROM {S}.{ST}
  WHERE {qident(c_time)} < '{cutoff}' AND {qident(c_status)} IN ({norm_sql})
),
agg AS (
  SELECT host, model, hour,
         MIN(battery_charge_percent) AS batt_min,
         MAX(battery_charge_percent) AS batt_max,
         (array_agg(battery_charge_percent ORDER BY t DESC))[1] AS batt_last,
         MIN(ups_load_percent) AS load_min,
         MAX(ups_load_percent) AS load_max,
         MIN(input_voltage) AS in_min,
         MAX(input_voltage) AS in_max,
         MIN(output_voltage) AS out_min,
         MAX(output_voltage) AS out_max,
         COUNT(*) AS cnt,
         MODE() WITHIN GROUP (ORDER BY ups_status) AS status_mode
  FROM base
  GROUP BY host, model, hour
)
SELECT host, model, hour, batt_min, batt_max, batt_last, load_min, load_max, in_min, in_max, out_min, out_max, cnt, status_mode
FROM agg
ORDER BY hour;
"""

    print('[INFO] scanning hourly aggregates for normal mode...')
    out_hr = psql(env, sql_hr, psql_bin, dry=False)
    hlines = [l for l in out_hr.strip().split('\n') if l.strip()]
    print(f'[INFO] found {len(hlines)} hourly buckets')

    if not dry and hlines:
        ins_hr = []
        for l in hlines:
            parts = l.split('\t')
            if len(parts) < 14:
                continue
            host, model, hour, batt_min, batt_max, batt_last, load_min, load_max, in_min, in_max, out_min, out_max, cnt, status_mode = parts[:14]

            def ni(x):
                try:
                    if x == '' or str(x).lower() == 'null':
                        return 'NULL'
                    return x
                except Exception:
                    return 'NULL'

            def ns(x):
                try:
                    if x == '' or str(x).lower() == 'null':
                        return 'NULL'
                    return "'" + str(x).replace("'", "''") + "'"
                except Exception:
                    return 'NULL'

            ins_hr.append(f"({ns(host)},{ns(model)},{ns(hour)},{ni(batt_min)},{ni(batt_max)},{ni(batt_last)},{ni(load_min)},{ni(load_max)},{ni(in_min)},{ni(in_max)},{ni(out_min)},{ni(out_max)},{ni(cnt)},{ns(status_mode)})")

        for i in range(0, len(ins_hr), batch_size):
            batch = ins_hr[i:i + batch_size]
            sql_ins = f"INSERT INTO {S}.{HT} (host,model,hour,batt_min,batt_max,batt_last,load_min,load_max,in_min,in_max,out_min,out_max,cnt,status_mode) VALUES {','.join(batch)} ON CONFLICT (host,model,hour) DO NOTHING;"
            psql(env, sql_ins, psql_bin, dry=False)
        print(f'[INFO] inserted/upserted {len(ins_hr)} hourly rows into {schema}.{hr}')

    if not dry:
        sql_del_ev2 = f"DELETE FROM {S}.{ST} WHERE {qident(c_time)} < '{cutoff}' AND {qident(c_status)} IN ({win_sql});"
        sql_del_hr = f"DELETE FROM {S}.{ST} WHERE {qident(c_time)} < '{cutoff}' AND {qident(c_status)} IN ({norm_sql}) AND NOT ({qident(c_status)} IN ({win_sql}));"
        print('[INFO] deleting compressed source rows...')
        psql(env, sql_del_ev2, psql_bin, dry=False)
        psql(env, sql_del_hr, psql_bin, dry=False)
        print('[INFO] deletion done')
    else:
        print('[DRY] would delete from %s.%s where %s < %s and (%s in %s OR %s in %s)' % (schema, src, c_time, cutoff, c_status, win, c_status, norm))

    print('[DONE]')


if __name__ == '__main__':
    main()
