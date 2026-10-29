"""Portable scheduling and duplicate-prevention helpers (no Windows dependencies)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import re
VN = timezone(timedelta(hours=7))
TASK_NAME = 'Jiayang-WeChat-PDF'
URL = 'https://42462949-code.github.io/jy-digital-management/'
DEFAULT = {'time': '00:17', 'recipients': [], 'username': 'admin', 'enabled': False, 'data_verified': False, 'calibrations': {}, 'tests': {}}

def validate(config):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', config['time']):
        raise ValueError('越南时间请填写 HH:MM，例如 00:17')
    recipients = config['recipients']
    if not recipients or len(recipients) != len(set(recipients)):
        raise ValueError('请填写至少一个收件人，且不要重复')
    if len(recipients) > 20 or any(not re.fullmatch(r'[A-Za-z0-9_+@.\-]{3,80}', r) for r in recipients):
        raise ValueError('请填写微信账号，一行一个（不要填昵称）')
    if not config.get('username', '').strip():
        raise ValueError('请填写管理系统用户名')

def next_boundary(clock, now=None):
    now = (now or datetime.now(VN)).astimezone(VN)
    hour, minute = map(int, clock.split(':'))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.isoformat(timespec='seconds')

def is_due(clock, now=None):
    now = (now or datetime.now(VN)).astimezone(VN)
    hour, minute = map(int, clock.split(':'))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return 0 <= (now-target).total_seconds() < 120

def save_config(path, config):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

class Ledger:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute('CREATE TABLE IF NOT EXISTS attempts(day TEXT,recipient TEXT,pdf TEXT,state TEXT,updated TEXT,PRIMARY KEY(day,recipient))')
        self.conn.commit()
    def reserve(self, day, recipient, pdf):
        try:
            self.conn.execute('INSERT INTO attempts VALUES (?,?,?,?,?)', (day,recipient,str(pdf),'send_started',datetime.now(VN).isoformat()))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    def finish(self, day, recipient, state):
        self.conn.execute('UPDATE attempts SET state=?,updated=? WHERE day=? AND recipient=?', (state,datetime.now(VN).isoformat(),day,recipient))
        self.conn.commit()
