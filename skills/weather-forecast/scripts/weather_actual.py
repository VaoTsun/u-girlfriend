#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path


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
    except Exception:
        pass


def load_env():
    env = {}
    p = Path('/home/vao/u-barn/.env')
    if not p.exists():
        p = Path(os.path.expanduser('~/u-barn/.env'))
    if p.exists():
        try:
            for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            log(f'WARN load_env {e}')
    return env


def load_cfg():
    if CFG.exists():
        return json.loads(CFG.read_text(encoding='utf-8'))
    if CFG_EX.exists():
        return json.loads(CFG_EX.read_text(encoding='utf-8'))
    return {}


def qv(s):
    if s is None:
        return 'NULL'
    if isinstance(s, bool):
        return 'true' if s else 'false'
    if isinstance(s, (int, float)):
        return str(s)
    return "'" + str(s).replace("'", "''") + "'"


def psql_run(sql, env_secrets, cfg_db=None):
    db_host = (cfg_db or {}).get('db_host') or env_secrets.get('PGHOST') or '192.168.88.171'
    db_user = (cfg_db or {}).get('db_user') or env_secrets.get('PGUSER') or 'app'
    db_name = (cfg_db or {}).get('db_name') or env_secrets.get('PGDATABASE') or 'd'
    env = os.environ.copy()
    env['PGPASSWORD'] = env_secrets.get('DB_PASSWORD') or env_secrets.get('PGPASSWORD') or ''
    proc = subprocess.run(['/usr/bin/psql', '-h', db_host, '-U', db_user, '-d', db_name, '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '|', '-c', sql],
                         capture_output=True, text=True, timeout=60, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f'psql exit {proc.returncode}')
    return proc.stdout


def main():
    try:
        cfg = load_cfg()
        out_src = cfg.get('outdoor_src')
        if out_src is None:
            log('SKIP: outdoor_src not set in config.json')
            return
        env_secrets = load_env()
        today = date.today()
        yesterday = today - timedelta(days=1)
        sql_vals = f"""
SELECT min(cels), max(cels), count(*)
FROM ar.vals
WHERE src = {int(out_src)}
  AND ts >= {qv(yesterday.isoformat())}::date
  AND ts < {qv(today.isoformat())}::date
  AND cels IS NOT NULL
"""
        out = psql_run(sql_vals, env_secrets)
        tmin = None
        tmax = None
        samples = 0
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                try:
                    if parts[0] and parts[0] != '':
                        tmin = float(parts[0])
                except Exception:
                    tmin = None
                try:
                    if parts[1] and parts[1] != '':
                        tmax = float(parts[1])
                except Exception:
                    tmax = None
                try:
                    samples = int(float(parts[2]))
                except Exception:
                    samples = 0
                break
        actual = {
            "filled_at": datetime.now().astimezone().isoformat(),
            "from": "ar.vals",
            "src": int(out_src),
            "tmin": tmin,
            "tmax": tmax,
            "samples": samples
        }
        data_init = {"actual": actual}
        sql_ins = f"""
INSERT INTO dev.weather (day, data, updated_at)
VALUES ({qv(yesterday.isoformat())}, {qv(json.dumps(data_init, ensure_ascii=False))}::jsonb, now())
ON CONFLICT (day) DO UPDATE SET
  data = jsonb_set(COALESCE(dev.weather.data, '{{}}'::jsonb), '{{actual}}', {qv(json.dumps(actual, ensure_ascii=False))}::jsonb, true),
  updated_at = now()
"""
        psql_run(sql_ins, env_secrets)
        log(f'OK actual {yesterday} src={out_src} tmin={tmin} tmax={tmax} samples={samples}')
    except Exception as e:
        log(f'ERR {e}')
        raise


if __name__ == '__main__':
    main()
