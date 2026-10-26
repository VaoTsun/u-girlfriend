#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
from datetime import datetime, date, timezone
from pathlib import Path
import urllib.request

BASE = Path(__file__).resolve().parent.parent
CFG = BASE / 'config.json'
CFG_EX = BASE / 'config.json.example'
LOG = BASE / 'weather_forecast.log'


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
    p = CFG if CFG.exists() else CFG_EX
    return json.loads(p.read_text(encoding='utf-8'))


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'u-barn-weather-forecast/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


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
    proc = subprocess.run(['/usr/bin/psql', '-h', db_host, '-U', db_user, '-d', db_name, '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-c', sql],
                         capture_output=True, text=True, timeout=60, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f'psql exit {proc.returncode}')
    return proc.stdout


def main():
    try:
        cfg = load_cfg()
        url = cfg.get('owm_url') or "https://api.openweathermap.org/data/2.5/forecast?q=Visaginas&appid=ab071a5ec4952f607a076c66ecdba01d&units=metric"
        city = cfg.get('city') or 'Visaginas'
        env_secrets = load_env()
        j = get_json(url)
        items = j.get('list') or []
        tmins = []
        tmaxs = []
        for it in items:
            m = it.get('main') or {}
            if m.get('temp_min') is not None:
                try:
                    tmins.append(float(m['temp_min']))
                except Exception:
                    pass
            if m.get('temp_max') is not None:
                try:
                    tmaxs.append(float(m['temp_max']))
                except Exception:
                    pass
        tmin = min(tmins) if tmins else None
        tmax = max(tmaxs) if tmaxs else None
        forecast = {"source": "openweathermap", "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(), "city": city, "tmin": tmin, "tmax": tmax, "items": items}
        today = date.today()
        data_init = {"forecast": forecast}
        sql = f"""
INSERT INTO dev.weather (day, data, updated_at)
VALUES ({qv(today.isoformat())}, {qv(json.dumps(data_init, ensure_ascii=False))}::jsonb, now())
ON CONFLICT (day) DO UPDATE SET
  data = jsonb_set(COALESCE(dev.weather.data, '{{}}'::jsonb), '{{forecast}}', {qv(json.dumps(forecast, ensure_ascii=False))}::jsonb, true),
  updated_at = now()
"""
        psql_run(sql, env_secrets)
        log(f'OK forecast {today} tmin={tmin} tmax={tmax}')
    except Exception as e:
        log(f'ERR {e}')
        raise


if __name__ == '__main__':
    main()
