#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime, date, timezone
from pathlib import Path
import urllib.request

try:
    import psycopg2
    from psycopg2.extras import Json
except Exception as e:
    print('ERR', e)
    sys.exit(1)

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
    p = CFG if CFG.exists() else CFG_EX
    return json.loads(p.read_text(encoding='utf-8'))

def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent':'u-barn-weather-forecast/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))

def main():
    try:
        cfg = load_cfg()
        url = cfg.get('owm_url') or "https://api.openweathermap.org/data/2.5/forecast?q=Visaginas&appid=ab071a5ec4952f607a076c66ecdba01d&units=metric"
        city = cfg.get('city') or 'Visaginas'
        env = load_env()
        conn = psycopg2.connect(
            host=env.get('PGHOST','192.168.88.171'),
            port=env.get('PGPORT','5432'),
            dbname=env.get('PGDATABASE','d'),
            user=env.get('PGUSER','app'),
            password=env.get('PGPASSWORD','')
        )
        cur = conn.cursor()
        j = get_json(url)
        items = j.get('list') or []
        tmins = []
        tmaxs = []
        for it in items:
            m = it.get('main') or {}
            if m.get('temp_min') is not None: tmins.append(float(m['temp_min']))
            if m.get('temp_max') is not None: tmaxs.append(float(m['temp_max']))
            if m.get('temp') is not None and not tmins and not tmaxs:
                pass
        tmin = min(tmins) if tmins else None
        tmax = max(tmaxs) if tmaxs else None
        forecast = {
            "source": "openweathermap",
            "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "city": city,
            "tmin": tmin,
            "tmax": tmax,
            "items": items
        }
        today = date.today()
        # мерджим: добавляем/обновляем forecast, actual не трогаем
        cur.execute("""
            INSERT INTO dev.weather (day, data, updated_at)
            VALUES (%s, %s::jsonb, now())
            ON CONFLICT (day) DO UPDATE SET
              data = jsonb_set(
                COALESCE(dev.weather.data, '{}'::jsonb),
                '{forecast}',
                %s::jsonb,
                true
              ),
              updated_at = now()
        """, (today, Json({"forecast": forecast}), Json(forecast)))
        conn.commit()
        cur.close()
        conn.close()
        log(f'OK forecast {today} tmin={tmin} tmax={tmax}')
    except Exception as e:
        log(f'ERR {e}')
        raise

if __name__=='__main__':
    main()
