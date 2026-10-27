#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import shutil
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

def run(cmd, env, dry=False):
    if dry:
        print('[DRY]', ' '.join(cmd))
        return 0, '', ''
    run_env = os.environ.copy()
    run_env.update(env)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=run_env)
    out, err = proc.communicate()
    return proc.returncode, out.decode('utf-8', errors='ignore'), err.decode('utf-8', errors='ignore')

def find_bin(name, pg_bin_dir=''):
    if pg_bin_dir:
        p = os.path.join(pg_bin_dir, name)
        if os.path.exists(p):
            return p
    p = shutil.which(name)
    return p or name

def main():
    ap = argparse.ArgumentParser(description='Backup schemas r and dev')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--config', help='Path to config.json')
    args = ap.parse_args()
    dry = args.dry_run

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env, cfg = get_db_env(skill_dir)
    if args.config and os.path.exists(args.config):
        with open(args.config,'r',encoding='utf-8') as f:
            cfg.update(json.load(f))

    db = env.get('PGDATABASE') or env.get('DB_NAME') or 'd'
    user = env.get('PGUSER') or env.get('DB_USER') or os.environ.get('USER') or 'app'
    password = env.get('PGPASSWORD') or env.get('DB_PASSWORD') or ''
    pghost = env.get('PGHOST') or env.get('DB_HOST') or ''
    pgport = env.get('PGPORT') or env.get('DB_PORT') or ''
    pg_bin_dir = cfg.get('pg_bin_dir','')
    backup_dir = cfg.get('backup_dir','/home/vao/backups/db')
    schemas = cfg.get('schemas',['ar','dev'])
    partial = cfg.get('partial_tables',[{"schema":"ar","table":"vals","days":7,"time_col":"time"}])
    keep_days = int(cfg.get('keep_days',14))

    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    outdir = os.path.join(backup_dir, ts)
    if not dry:
        os.makedirs(outdir, exist_ok=True)
    print(f'[INFO] backup to {outdir}')

    pg_dump = find_bin('pg_dump', pg_bin_dir)
    psql = find_bin('psql', pg_bin_dir)

    env_run = {}
    if password:
        env_run['PGPASSWORD'] = password

    base = [pg_dump]
    if pghost and pghost not in ('127.0.0.1','localhost'):
        base += ['-h', pghost]
    elif pghost in ('127.0.0.1','localhost'):
        pass
    if pgport:
        base += ['-p', str(pgport)]
    base += ['-U', user, '-d', db, '-Fc']

    # get tables
    q = "SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN (%s) ORDER BY schemaname, tablename;" % ','.join(["'%s'"%s.replace("'","''") for s in schemas])
    rc, out, err = run([psql] + (['-h',pghost] if pghost and pghost not in ('127.0.0.1','localhost') else []) + (['-p',str(pgport)] if pgport and pghost not in ('127.0.0.1','localhost') else []) + ['-U',user,'-d',db,'-t','-A','-F','\t','-c',q], env_run, dry)
    if rc != 0 and not dry:
        print('[ERR]', err)
        sys.exit(rc)

    tables = []
    for l in out.strip().split('\n'):
        if not l.strip(): continue
        s,t = l.split('\t')
        tables.append((s,t))

    part_map = {}
    for p in partial:
        part_map[(p['schema'], p['table'])] = p

    for s,t in tables:
        key = (s,t)
        if key in part_map:
            pinfo = part_map[key]
            days = int(pinfo.get('days',7))
            tcol = pinfo.get('time_col','time')
            cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            where = f"\"{tcol}\" >= '{cutoff}'"
            cmd = base + ['-t', f'{s}.{t}', f'--where={where}', '-f', os.path.join(outdir, f'{s}.{t}.partial.{days}d.{ts}.dump')]
            print(f'[INFO] partial {s}.{t} last {days}d')
            rc,e,er = run(cmd, env_run, dry)
            if rc != 0 and not dry:
                print('[ERR]', er)
        else:
            cmd = base + ['-t', f'{s}.{t}', '-f', os.path.join(outdir, f'{s}.{t}.full.{ts}.dump')]
            print(f'[INFO] full {s}.{t}')
            rc,e,er = run(cmd, env_run, dry)
            if rc != 0 and not dry:
                print('[ERR]', er)

    # cleanup
    if not dry and os.path.exists(backup_dir):
        cutoff_d = datetime.now() - timedelta(days=keep_days)
        for name in os.listdir(backup_dir):
            dpath = os.path.join(backup_dir, name)
            if os.path.isdir(dpath):
                try:
                    st = os.stat(dpath)
                    mtime = datetime.fromtimestamp(st.st_mtime)
                    if mtime < cutoff_d:
                        print(f'[INFO] removing old backup {dpath}')
                        shutil.rmtree(dpath)
                except Exception as ex:
                    print(f'[WARN] cleanup {dpath}: {ex}')
    print('[DONE]')

if __name__ == '__main__':
    main()
