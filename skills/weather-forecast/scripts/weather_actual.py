#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import Json
except Exception as e:
    print('ERR', e)
    sys.exit(1)

BASE = Path(__file__).resolve().parent.parent
CFG = BASE / 'config.json'
CFG_EX = BASE / 'config.json.example'
LOG = BASE / 'weather_actual.log'

def log(m):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {m}'
    print(line)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except:
        pass

def load_env():
    env = {}
    p = Path('/home/vao/u-barn/.env')
    if not p.exists():
        p = Path(os.path.expanduser('~/u-barn/.env'))
    if p.exists():
        for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                k,v = line.split('=',1)
                env[k.strip()]=v.strip().strip('"').strip("'")
    return env

def load_cfg():
    if CFG.exists():
        return json.loads(CFG.read_text(encoding='utf-8'))
    if CFG_EX.exists():
        return json.loads(CFG_EX.read_text(encoding='utf-8'))
    return {}

def main():
    try:
        cfg = load_cfg()
        out_src = cfg.get('outdoor_src')
        if out_src is None:
            log('SKIP: outdoor_src not set in config.json')
            return
        env = load_env()
        conn = psycopg2.connect(
            host=env.get('PGHOST','192.168.88.171'),
            port=env.get('PGPORT','5432'),
            dbname=env.get('PGDATABASE','d'),
            user=env.get('PGUSER','app'),
            password=env.get('PGPASSWORD','')
        )
        cur = conn.cursor()
        # считаем за вчерашние сутки по местному времени примерно
        today = date.today()
        yesterday = today - timedelta(days=1)
        cur.execute("""
            SELECT min(cels), max(cels), count(*)
            FROM ar.vals
            WHERE src = %s
              AND ts >= (%s::date)
              AND ts < (%s::date)
              AND cels IS NOT NULL
        """, (out_src, yesterday, today))
        row = cur.fetchone()
        tmin = float(row[0]) if row and row[0] is not None else None
        tmax = float(row[1]) if row and row[1] is not None else None
        samples = int(row[2]) if row and row[2] is not None else 0
        actual = {
            "filled_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "from": "ar.vals",
            "src": int(out_src),
            "tmin": tmin,
            "tmax": tmax,
            "samples": samples
        }
        cur.execute("""
            INSERT INTO dev.weather (day, data, updated_at)
            VALUES (%s, %s::jsonb, now())
            ON CONFLICT (day) DO UPDATE SET
              data = jsonb_set(
                COALESCE(dev.weather.data, '{}'::jsonb),
                '{actual}',
                %s::jsonb,
                true
              ),
              updated_at = now()
        """, (yesterday, Json({"actual": actual}), Json(actual)))
        conn.commit()
        cur.close()
        conn.close()
        log(f'OK actual {yesterday} src={out_src} tmin={tmin} tmax={tmax} samples={samples}')
    except Exception as e:
        log(f'ERR {e}')
        raise

if __name__=='__main__':
    main()
