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
    # inherit from environment
    for k in ['PGHOST','PGPORT','PGUSER','PGPASSWORD','PGDATABASE','DB_PASSWORD','DB_USER','DB_NAME','DB_HOST']:
        if k in os.environ and k not in env:
            env[k] = os.environ[k]
    return env, cfg

def psql(env, sql, psql_bin='psql', dry=False):
    if dry:
        print('[DRY] SQL:\n' + sql)
        return ''
    db = env.get('PGDATABASE') or env.get('DB_NAME') or 'd'
    user = env.get('PGUSER') or env.get('DB_USER') or os.environ.get('USER') or 'app'
    password = env.get('PGPASSWORD') or env.get('DB_PASSWORD') or ''

    # Try to connect via Unix socket first (like on prod without pgpass)
    cmd = [psql_bin, '-d', db, '-U', user, '-v', 'ON_ERROR_STOP=1', '-t', '-A']
    # If PGHOST explicitly set and not empty, use TCP; else prefer socket
    pghost = env.get('PGHOST') or env.get('DB_HOST') or ''
    if pghost and pghost not in ('', 'localhost', '127.0.0.1'):
        cmd.extend(['-h', pghost])
        if env.get('PGPORT') or env.get('DB_PORT'):
            cmd.extend(['-p', str(env.get('PGPORT') or env.get('DB_PORT'))])
    elif pghost in ('127.0.0.1','localhost'):
        # prefer socket on same host
        pass

    run_env = os.environ.copy()
    if password:
        run_env['PGPASSWORD'] = password
    proc = subprocess.Popen(cmd + ['-c', sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=run_env)
    out, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f'psql failed: {err.decode("utf-8", errors="ignore")}')
    return out.decode('utf-8', errors='ignore')

def qident(s):
    return '"' + s.replace('"','""') + '"'

def main():
    ap = argparse.ArgumentParser(description='Compress dev.upsd into events/hourly')
    ap.add_argument('--apply', action='store_true', help='Actually insert/delete (default: dry-run)')
    ap.add_argument('--config', help='Path to config.json')
    args = ap.parse_args()
    dry = not args.apply

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
    win_sql = ','.join(["'%s'" % w.replace("'","''") for w in win])
    norm_sql = ','.join(["'%s'" % n.replace("'","''") for n in norm])

    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[INFO] mode={'DRY-RUN' if dry else 'APPLY'} keep_days={keep_days} cutoff<{cutoff}")
    dbn = env.get('PGDATABASE') or env.get('DB_NAME')
    pgu = env.get('PGUSER') or env.get('DB_USER')
    pgh = env.get('PGHOST') or env.get('DB_HOST') or '(socket)'
    pgp = env.get('PGPORT') or env.get('DB_PORT') or ''
    print(f"[INFO] db={dbn}@{pgh}{(':'+pgp) if pgp else ''} user={pgu}")
    print(f"[INFO] tables: {schema}.{src} -> {schema}.{ev}, {schema}.{hr}")
    print(f"[INFO] window_statuses={win} normal_statuses={norm}")

    # 1) Find event windows (consecutive rows in window_statuses per host/model)
    sql_win = f"""
WITH ordered AS (
  SELECT host, model, "time", ups_status, battery_charge_percent, ups_load_percent, input_voltage, output_voltage,
         ROW_NUMBER() OVER (PARTITION BY host, model ORDER BY "time") AS rn,
         ROW_NUMBER() OVER (PARTITION BY host, model, CASE WHEN ups_status IN ({win_sql}) THEN 1 ELSE 0 END ORDER BY "time") AS grp
  FROM {S}.{ST}
  WHERE "time" < '{cutoff}'
),
windows AS (
  SELECT host, model, MIN("time") AS started_at, MAX("time") AS ended_at,
         COUNT(*) AS cnt,
         ARRAY_AGG(ups_status ORDER BY "time") AS statuses,
         MIN(battery_charge_percent) AS batt_min,
         MAX(battery_charge_percent) AS batt_max,
         MIN(battery_charge_percent) FILTER (WHERE rn = MIN(rn) OVER (PARTITION BY host, model, grp)) AS batt_start,
         MIN(battery_charge_percent) FILTER (WHERE rn = MAX(rn) OVER (PARTITION BY host, model, grp)) AS batt_end,
         MAX(ups_load_percent) AS load_max,
         MIN(input_voltage) AS in_min, MAX(input_voltage) AS in_max,
         MIN(output_voltage) AS out_min, MAX(output_voltage) AS out_max
  FROM ordered
  WHERE ups_status IN ({win_sql})
  GROUP BY host, model, grp
)
SELECT host, model, started_at, ended_at, EXTRACT(EPOCH FROM (ended_at - started_at))::int AS duration_sec,
       batt_start, batt_min, batt_end, load_max, in_min, in_max, out_min, out_max, cnt, statuses
FROM windows
ORDER BY started_at;
"""
    print('[INFO] scanning event windows...')
    out_win = psql(env, sql_win, psql_bin, dry=False)  # always read
    lines = [l for l in out_win.strip().split('\n') if l.strip()]
    print(f'[INFO] found {len(lines)} event windows')

    if not dry and lines:
        ins_ev = []
        for l in lines:
            # parse tab-separated
            parts = l.split('\t')
            if len(parts) < 15: continue
            host, model, started_at, ended_at, duration_sec, batt_start, batt_min, batt_end, load_max, in_min, in_max, out_min, out_max, cnt, statuses = parts[:15]
            # map type
            st0 = statuses.strip('{}').split(',')[0].strip('"')
            tmap = {'OB':'on_batt','DISCHRG':'on_batt','ALARM':'alarm','LB':'low_batt'}
            etype = tmap.get(st0,'other')
            def ni(x): 
                try: return 'NULL' if x=='' or x.lower()=='null' else x
                except: return 'NULL'
            def ns(x):
                try: 
                    if x=='' or x.lower()=='null': return 'NULL'
                    return "'%s'" % str(x).replace("'","''")
                except: return 'NULL'
            details = json.dumps({'statuses': statuses.strip('{}').replace('"','').split(',') if statuses else []}).replace("'","''")
            ins_ev.append(f"({ns(host)},{ns(model)},{ns(started_at)},{ns(ended_at)},'{etype}',{ni(batt_start)},{ni(batt_min)},{ni(batt_end)},{ni(load_max)},{ni(in_min)},{ni(in_max)},{ni(out_min)},{ni(out_max)},{ni(duration_sec)},'{details}'::jsonb)")
        # insert in batches
        for i in range(0, len(ins_ev), batch_size):
            batch = ins_ev[i:i+batch_size]
            sql_ins = f"INSERT INTO {S}.{ET} (host,model,started_at,ended_at,type,batt_start,batt_min,batt_end,load_max,in_min,in_max,out_min,out_max,duration_sec,details) VALUES {','.join(batch)};"
            psql(env, sql_ins, psql_bin, dry=False)
        print(f'[INFO] inserted {len(ins_ev)} events into {schema}.{ev}')

    # 2) Hourly aggregates for normal statuses
    sql_hr = f"""
WITH base AS (
  SELECT host, model, date_trunc('hour', "time") AS hour, ups_status, battery_charge_percent, ups_load_percent, input_voltage, output_voltage, "time"
  FROM {S}.{ST}
  WHERE "time" < '{cutoff}' AND ups_status IN ({norm_sql})
),
agg AS (
  SELECT host, model, hour,
         MIN(battery_charge_percent) AS batt_min,
         MAX(battery_charge_percent) AS batt_max,
         (array_agg(battery_charge_percent ORDER BY "time" DESC))[1] AS batt_last,
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
            if len(parts) < 14: continue
            host, model, hour, batt_min, batt_max, batt_last, load_min, load_max, in_min, in_max, out_min, out_max, cnt, status_mode = parts[:14]
            def ni(x): 
                try: return 'NULL' if x=='' or x.lower()=='null' else x
                except: return 'NULL'
            def ns(x):
                try: 
                    if x=='' or x.lower()=='null': return 'NULL'
                    return "'%s'" % str(x).replace("'","''")
                except: return 'NULL'
            ins_hr.append(f"({ns(host)},{ns(model)},{ns(hour)},{ni(batt_min)},{ni(batt_max)},{ni(batt_last)},{ni(load_min)},{ni(load_max)},{ni(in_min)},{ni(in_max)},{ni(out_min)},{ni(out_max)},{ni(cnt)},{ns(status_mode)})")
        for i in range(0, len(ins_hr), batch_size):
            batch = ins_hr[i:i+batch_size]
            sql_ins = f"INSERT INTO {S}.{HT} (host,model,hour,batt_min,batt_max,batt_last,load_min,load_max,in_min,in_max,out_min,out_max,cnt,status_mode) VALUES {','.join(batch)} ON CONFLICT (host,model,hour) DO NOTHING;"
            psql(env, sql_ins, psql_bin, dry=False)
        print(f'[INFO] inserted/upserted {len(ins_hr)} hourly rows into {schema}.{hr}')

    # 3) Delete from source (only after inserts in apply mode)
    if not dry:
        # delete event windows rows
        sql_del_ev = f"""
DELETE FROM {S}.{ST} s
WHERE s."time" < '{cutoff}'
  AND EXISTS (
    SELECT 1 FROM (
      SELECT host, model, "time", ROW_NUMBER() OVER (PARTITION BY host, model, CASE WHEN ups_status IN ({win_sql}) THEN 1 ELSE 0 END ORDER BY "time") AS grp
      FROM {S}.{ST}
      WHERE "time" < '{cutoff}'
    ) x
    WHERE x.host=s.host AND x.model=s.model AND x."time"=s."time" AND x.grp IN (
      SELECT grp FROM (
        SELECT host, model, grp FROM (
          SELECT host, model, "time", ups_status, ROW_NUMBER() OVER (PARTITION BY host, model, CASE WHEN ups_status IN ({win_sql}) THEN 1 ELSE 0 END ORDER BY "time") AS grp
          FROM {S}.{ST}
          WHERE "time" < '{cutoff}'
        ) y WHERE ups_status IN ({win_sql}) GROUP BY host, model, grp
      ) g
    )
    AND s.ups_status IN ({win_sql})
  );
"""
        # simpler: delete all window rows < cutoff
        sql_del_ev2 = f"DELETE FROM {S}.{ST} WHERE \"time\" < '{cutoff}' AND ups_status IN ({win_sql});"
        sql_del_hr = f"DELETE FROM {S}.{ST} WHERE \"time\" < '{cutoff}' AND ups_status IN ({norm_sql}) AND NOT (ups_status IN ({win_sql}));"
        print('[INFO] deleting compressed source rows...')
        psql(env, sql_del_ev2, psql_bin, dry=False)
        psql(env, sql_del_hr, psql_bin, dry=False)
        print('[INFO] deletion done')
    else:
        print('[DRY] would delete from %s.%s where time < %s and (ups_status in %s OR ups_status in %s)' % (schema,src,cutoff,win,norm))

    print('[DONE]')

if __name__ == '__main__':
    main()
