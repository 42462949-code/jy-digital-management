"""Authenticated, idempotent scan-report API. Put behind HTTPS (Caddy provided)."""
import datetime as dt
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIELDS = ['扫码时间','日期','工序','组别','客户','客户指令单','品名及加工明细','规格','数量','备注']
ID = re.compile(r'^[A-Za-z0-9_-]{16,120}$')
DB = os.environ.get('JY_DB_PATH', '/data/reports.sqlite3')
ALLOWED = set(filter(None, os.environ.get('JY_ALLOWED_ORIGINS','https://42462949-code.github.io').split(',')))
USER = os.environ.get('JY_ADMIN_USER', 'admin')
PASSWORD = os.environ.get('JY_ADMIN_PASSWORD', '')
SALT = secrets.token_bytes(32)
PASSWORD_HASH = hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), SALT, 300000)
ATTEMPTS = defaultdict(deque)
RATE_LOCK = threading.Lock()

def connect():
    con = sqlite3.connect(DB, timeout=30)
    con.execute('PRAGMA busy_timeout=30000')
    con.execute('PRAGMA foreign_keys=ON')
    return con

def initialize():
    if len(PASSWORD) < 8:
        raise RuntimeError('Set JY_ADMIN_PASSWORD to at least 8 characters in the server environment')
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL, username TEXT NOT NULL, received_at TEXT NOT NULL)')
        if 'unit' not in {column[1] for column in con.execute('PRAGMA table_info(reports)')}:
            con.execute("ALTER TABLE reports ADD COLUMN unit TEXT NOT NULL DEFAULT ''")
        con.execute('CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, signature TEXT NOT NULL, response TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        fingerprint = hashlib.sha256((USER+'\0'+PASSWORD).encode()).hexdigest()
        old = con.execute("SELECT value FROM settings WHERE key='account'").fetchone()
        if not old or old[0] != fingerprint:
            con.execute('DELETE FROM sessions')
            con.execute("INSERT OR REPLACE INTO settings VALUES ('account',?)", (fingerprint,))
        con.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))

def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',',':'), sort_keys=True)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def validate(records):
    if not isinstance(records,list) or not 1 <= len(records) <= 200:
        raise ValueError('每次提交必须包含1至200条记录')
    output = []
    seen = set()
    for record in records:
        if not isinstance(record,dict) or not isinstance(record.get('id'),str) or not ID.fullmatch(record['id']) or record['id'] in seen:
            raise ValueError('记录标识无效或重复')
        seen.add(record['id'])
        values = record.get('values')
        if not isinstance(values,list) or len(values) != 10:
            raise ValueError('扫码记录必须包含10个字段')
        values = values.copy()
        for i, value in enumerate(values):
            if i == 8:
                if isinstance(value,bool) or not isinstance(value,(str,int,float)) or str(value).strip() == '':
                    raise ValueError('数量无效')
                values[i] = float(value)
                if not math.isfinite(values[i]) or values[i] < 0:
                    raise ValueError('数量无效')
            elif not isinstance(value,str) or len(value) > (16384 if i == 6 else 4096):
                raise ValueError('扫码字段无效或内容过长')
        dt.datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
        dt.datetime.strptime(values[1], '%Y-%m-%d')
        unit = record.get('unit','')
        if not isinstance(unit,str) or len(unit)>80:
            raise ValueError('单位无效')
        output.append({'id':record['id'],'values':values,'unit':unit})
    return output

class Handler(BaseHTTPRequestHandler):
    server_version = 'JYReports/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, fmt, *args):
        # Avoid logging request bodies, credentials, query values, or tokens.
        pass

    def origin_allowed(self):
        return not self.headers.get('Origin') or self.headers.get('Origin') in ALLOWED

    def reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        origin = self.headers.get('Origin')
        if origin in ALLOWED:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary','Origin')
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        if not self.origin_allowed():
            return self.reply(403, {'error':'不允许此来源'})
        self.send_response(204)
        if self.headers.get('Origin') in ALLOWED:
            self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
            self.send_header('Vary','Origin')
        self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type,Authorization')
        self.send_header('Access-Control-Max-Age','600')
        self.end_headers()

    def user(self):
        token = self.headers.get('Authorization','').removeprefix('Bearer ')
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with connect() as con:
            result = con.execute('SELECT username FROM sessions WHERE token_hash=? AND expires>?',(token_hash,time.time())).fetchone()
        return result[0] if result else None

    def read_body(self):
        if not self.headers.get('Content-Type','').lower().startswith('application/json'):
            raise ValueError('需要JSON请求')
        size = int(self.headers.get('Content-Length','0'))
        if not 0 < size <= 2*1024*1024:
            raise ValueError('请求为空或过大')
        data = json.loads(self.rfile.read(size))
        if not isinstance(data,dict):
            raise ValueError('请求格式错误')
        return data

    def do_GET(self):
        if not self.origin_allowed():
            return self.reply(403, {'error':'不允许此来源'})
        parsed = urlparse(self.path)
        if parsed.path == '/api/health':
            return self.reply(200, {'ok':True})
        if parsed.path != '/api/scan-reports':
            return self.reply(404, {'error':'接口不存在'})
        if not self.user():
            return self.reply(401, {'error':'请登录报工后台'})
        try:
            query = parse_qs(parsed.query)
            limit = max(1,min(200,int(query.get('limit',['200'])[0])))
            offset = max(0,int(query.get('offset',['0'])[0]))
            with connect() as con:
                rows = con.execute('SELECT id,payload,received_at,username,unit FROM reports ORDER BY received_at DESC,id LIMIT ? OFFSET ?',(limit,offset)).fetchall()
                count = con.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
            return self.reply(200, {'fields':FIELDS,'total':count,'records':[{'id':r[0],'values':json.loads(r[1]),'receivedAt':r[2],'username':r[3],'unit':r[4]} for r in rows]})
        except ValueError:
            return self.reply(400, {'error':'分页参数错误'})

    def do_POST(self):
        if not self.origin_allowed():
            return self.reply(403, {'error':'不允许此来源'})
        path = urlparse(self.path).path
        if path not in ['/api/login','/api/scan-reports']:
            return self.reply(404, {'error':'接口不存在'})
        try:
            body = self.read_body()
            if path == '/api/login':
                now = time.time()
                with RATE_LOCK:
                    attempts = ATTEMPTS[self.client_address[0]]
                    while attempts and attempts[0] < now-60:
                        attempts.popleft()
                    if len(attempts) >= 20:
                        return self.reply(429, {'error':'登录尝试过多，请稍后再试'})
                    attempts.append(now)
                username,password = body.get('username'),body.get('password')
                if not isinstance(username,str) or not isinstance(password,str) or len(password)>256:
                    return self.reply(401, {'error':'用户名或密码不正确'})
                candidate = hashlib.pbkdf2_hmac('sha256',password.encode(),SALT,300000)
                if not hmac.compare_digest(username,USER) or not hmac.compare_digest(candidate,PASSWORD_HASH):
                    return self.reply(401, {'error':'用户名或密码不正确'})
                token = secrets.token_urlsafe(32)
                expires = now+12*3600
                with connect() as con:
                    con.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),USER,expires))
                return self.reply(200, {'token':token,'expiresAt':dt.datetime.fromtimestamp(expires,dt.timezone.utc).isoformat()})
            username = self.user()
            if not username:
                return self.reply(401, {'error':'请登录报工后台'})
            batch = body.get('batchId')
            if not isinstance(batch,str) or not ID.fullmatch(batch):
                raise ValueError('批次标识无效')
            records = validate(body.get('records'))
            signature = digest(records)
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            response = {'batchId':batch,'acceptedIds':[r['id'] for r in records],'receivedAt':now}
            with connect() as con:
                con.execute('BEGIN IMMEDIATE')
                prior = con.execute('SELECT signature,response FROM batches WHERE id=?',(batch,)).fetchone()
                if prior:
                    legacy_signature = digest([{'id':r['id'],'values':r['values']} for r in records]) if all(not r['unit'] for r in records) else signature
                    if prior[0] not in (signature,legacy_signature):
                        return self.reply(409, {'error':'批次内容已改变，请重新核对'})
                    return self.reply(200,json.loads(prior[1]))
                for record in records:
                    payload = canonical(record['values'])
                    checksum = digest({'values':record['values'],'unit':record['unit']})
                    existing = con.execute('SELECT signature FROM reports WHERE id=?',(record['id'],)).fetchone()
                    legacy_checksum = digest(record['values']) if not record['unit'] else checksum
                    if existing and existing[0] not in (checksum,legacy_checksum):
                        con.rollback()
                        return self.reply(409, {'error':'记录已提交且内容不同，请联系管理员'})
                    if not existing:
                        con.execute('INSERT INTO reports (id,payload,signature,username,received_at,unit) VALUES (?,?,?,?,?,?)',(record['id'],payload,checksum,username,now,record['unit']))
                con.execute('INSERT INTO batches VALUES (?,?,?)',(batch,signature,canonical(response)))
            return self.reply(200,response)
        except (ValueError,TypeError,OverflowError):
            return self.reply(400, {'error':'扫码数据格式无效，请检查10个字段及数量'})
        except sqlite3.Error:
            return self.reply(503, {'error':'后台暂时无法保存，请稍后重试'})

if __name__ == '__main__':
    initialize()
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8000'))),Handler).serve_forever()
