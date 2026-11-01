"""Same-origin enterprise API; local/browser permissions are never trusted."""
import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from psycopg.types.json import Jsonb

from .work_state import work_state
from .db import (ACTIONS, BUSINESS_TABLES, CATALOG, PASSWORDS, TEAM_COLUMN, UTC7, Store,
                 audit, canonical, effective_permissions, in_scope, is_admin,
                 public_record, scopes, token_hash, validate_password)


@dataclass
class Config:
    database_url: str
    origin: str = 'http://127.0.0.1:8765'
    secure_cookie: bool = True
    static_root: Path = Path(__file__).resolve().parent.parent
    bootstrap_username: str = ''
    bootstrap_password: str = ''


def fail(code, message):
    raise HTTPException(code, message)


def uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        fail(400, '记录标识无效')


def text(value, name, maximum=200, blank=False):
    if not isinstance(value, str) or len(value) > maximum or (not blank and not value.strip()):
        fail(400, name + '无效')
    return value.strip()


def normalize_information(value):
    return text(value, '信息录入', 4096, True).replace('、', '\\')


def number(value):
    try:
        n = float(str(value).replace(',', '').replace('，', '').strip())
        if not math.isfinite(n):
            raise ValueError()
        return n
    except (ValueError, TypeError):
        fail(400, '数量无效')


def quantity_text(value):
    s = str(value).replace(',', '').replace('，', '').strip()
    return re.sub(r'(\.\d*?[1-9])0+$|\.0+$', r'\1', s)


def user_public(con, user):
    return {key: user[key] for key in ['username', 'name', 'department', 'team_ids', 'role_ids',
                                     'enabled', 'must_change_password', 'version', 'created_at', 'last_login_at']} | {
        'id': str(user['id']), 'admin': is_admin(con, user), 'permissions': effective_permissions(con, user)}


def current_user(request, con, password_ok=False):
    raw = request.cookies.get('jy_session', '')
    session = con.execute('SELECT * FROM jy_sessions WHERE token_hash=%s AND expires_at>now()', (token_hash(raw),)).fetchone()
    if not session:
        fail(401, '请登录系统')
    user = con.execute('SELECT * FROM jy_users WHERE id=%s AND enabled=true', (session['user_id'],)).fetchone()
    if not user:
        fail(401, '账号已停用或会话已失效')
    request.state.actor = {'id': user['id'], 'username': user['username']}
    if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session['csrf']):
        fail(403, '请求校验失败，请重新登录')
    if user['must_change_password'] and not password_ok:
        fail(403, '请先修改初始密码')
    return user, session


def require(con, user, table, action, record=None):
    allowed = scopes(con, user, table, action)
    if not allowed or (record and (not in_scope(user, record, allowed) or
                                  not in_scope(user, record, scopes(con, user, table, 'view')))):
        fail(403, '没有此操作或数据范围的权限')
    return allowed


def administrator(con, user):
    if not is_admin(con, user):
        fail(403, '仅系统管理员可操作')


def record_by_id(con, record_id, table=None):
    row = con.execute('SELECT * FROM jy_records WHERE id=%s', (uid(record_id),)).fetchone()
    if not row or (table is not None and row['table_id'] != table):
        fail(404, '记录不存在或不可访问')
    return row


def visible_rows(con, user, table, action='view'):
    allowed = require(con, user, table, action)
    conditions, args = [], [table]
    if 'all' not in allowed:
        if 'own' in allowed:
            conditions.append('owner_id=%s'); args.append(user['id'])
        if 'teams' in allowed and user['team_ids']:
            conditions.append('team_id=ANY(%s::uuid[])'); args.append(user['team_ids'])
        if 'department' in allowed and user['department']:
            conditions.append('department=%s'); args.append(user['department'])
    where = '' if 'all' in allowed else ' AND (' + (' OR '.join(conditions) or 'false') + ')'
    return con.execute('SELECT * FROM jy_records WHERE table_id=%s' + where + ' ORDER BY created_at DESC,id', args).fetchall()


def validate_values(table, values):
    if table==2 and isinstance(values,list) and len(values) in [17,18]: values=values+['']*(20-len(values))
    if table==4 and isinstance(values,list) and len(values)==10: values=values+['']*4
    if table==8 and isinstance(values,list) and len(values)==10: values=values+['','']
    if table==1 and isinstance(values,list) and len(values)==14: values=values+['']
    if table not in BUSINESS_TABLES or not isinstance(values, list) or len(values) != len(CATALOG[str(table)]['fields']):
        fail(400, '表或字段数量不匹配')
    for value in values:
        if type(value) not in (str, int, float) or (isinstance(value, str) and len(value) > 16384) or (isinstance(value, float) and not math.isfinite(value)):
            fail(400, '单元格数据无效')
    return values.copy()


def resolve_team(con, user, table, values, action, prior=None):
    column = TEAM_COLUMN.get(table)
    if column is None:
        return prior.get('team_id') if prior else None
    name = str(values[column]).strip()
    matches = con.execute("SELECT id FROM jy_records WHERE table_id=9 AND btrim(values_json->>2)=%s", (name,)).fetchall() if name else []
    if name and len(matches) != 1:
        fail(400, '机台或班组未维护，或班组名称重复')
    team = str(matches[0]['id']) if matches else None
    allowed = scopes(con, user, table, action)
    if 'all' not in allowed and (not team or team not in user['team_ids']):
        fail(403, '不能操作未分配的生产班组')
    return team


def insert_record(con, user, table, values, information='', meta=None, team_id=None, action='record.create', record_id=None):
    if table==2 and len(values) in [17,18]: values=values+['']*(20-len(values))
    if table==4 and len(values)==10:values=values+['']*4
    if table==8 and len(values)==10: values=values+['','']
    if table==1 and len(values)==14: values=values+[(meta or {}).get('documentNo','')]
    if table==1: meta={**(meta or {}),**work_state(values,(meta or {}).get('workStatus'))}
    record_id = uid(record_id) if record_id else str(uuid.uuid4())
    from .business_rules import attendance,production,price
    try:
        if table==2:values=production(values)
        if table==4:
            team=con.execute('SELECT values_json FROM jy_records WHERE id=%s',(team_id,)).fetchone() if team_id else None
            values=attendance(values,record_id,user['username'],department=team['values_json'][1] if team else values[11])
        if table==10:
            values,price_key=price(values,record_id);meta={**(meta or {}),'priceStatus':'未审核','priceKey':price_key}
    except ValueError as error:fail(400,str(error))

    con.execute('INSERT INTO jy_records(id,table_id,values_json,information,meta,owner_id,department,team_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                (record_id, table, Jsonb(values), normalize_information(information), Jsonb(meta or {}), user['id'], user['department'], team_id))
    audit(con, user, action, table, record_id, after={'values': values, 'information': information})
    return record_by_id(con, record_id, table)


def ensure_last_admin(con):
    rows = con.execute('SELECT * FROM jy_users WHERE enabled=true').fetchall()
    if not any(is_admin(con, user) for user in rows):
        fail(409, '必须保留至少一位启用的系统管理员')


async def body(request):
    if request.headers.get('Content-Type', '').split(';')[0] != 'application/json':
        fail(415, '需要JSON请求')
    raw = await request.body()
    if len(raw) > 64 * 1024 * 1024:
        fail(413, '请求过大，请分批处理')
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError()
        return parsed
    except (ValueError, UnicodeDecodeError):
        fail(400, '请求格式无效')


def create_app(config=None):
    cfg = config or Config(os.environ['DATABASE_URL'], os.environ.get('JY_PUBLIC_ORIGIN', ''),
                           os.environ.get('JY_DEVELOPMENT') != '1',
                           bootstrap_username=os.environ.get('JY_BOOTSTRAP_USER', ''),
                           bootstrap_password=os.environ.get('JY_BOOTSTRAP_PASSWORD', ''))
    if not cfg.origin or (cfg.secure_cookie and not cfg.origin.startswith('https://')):
        raise RuntimeError('正式部署必须配置HTTPS的JY_PUBLIC_ORIGIN')
    store = Store(cfg.database_url)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        if cfg.bootstrap_username and cfg.bootstrap_password:
            with store.connect() as con:
                empty = not con.execute('SELECT 1 FROM jy_users LIMIT 1').fetchone()
            if empty:
                store.bootstrap(cfg.bootstrap_username, cfg.bootstrap_password)
        from .business_workflows import snapshot_worker
        worker=asyncio.create_task(snapshot_worker(store))
        try:
            yield
        finally:
            worker.cancel()
            try:await worker
            except asyncio.CancelledError:pass

    app = FastAPI(title='Jiayang Enterprise', docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store, app.state.config = store, cfg

    @app.middleware('http')
    async def security(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('Origin') != cfg.origin:
            return JSONResponse({'error': '不允许的请求来源'}, 403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        actor=getattr(request.state,'actor',None)
        if actor and actor.get('id'):
            response.headers['X-JY-User-Id']=str(actor['id'])
        if response.status_code == 403:
            with store.connect(write=True) as con:
                audit(con, getattr(request.state, 'actor', {'username': 'anonymous'}), 'access.denied', after={'path': request.url.path})
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({'error': str(exc.detail)}, exc.status_code)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'error': str(exc)}, 400)

    @app.exception_handler(psycopg.IntegrityError)
    async def conflict_error(request, exc):
        return JSONResponse({'error': '名称、账号或记录冲突，请刷新后重试'}, 409)

    @app.get('/api/health')
    def health():
        with store.connect() as con:
            ready = bool(con.execute('SELECT 1 FROM jy_users LIMIT 1').fetchone())
        return {'ok': True, 'initialized': ready}

    @app.post('/api/auth/login')
    async def login(request: Request):
        data = await body(request)
        username = text(data.get('username'), '账号', 100)
        password = data.get('password')
        if not isinstance(password, str) or len(password) > 128:
            fail(401, '用户名或密码不正确')
        fingerprint = token_hash((request.client.host if request.client else '') + ':' + username)
        with store.connect(write=True) as con:
            con.execute("DELETE FROM jy_login_attempts WHERE attempted_at<now()-interval '1 day'")
            attempts = con.execute("SELECT count(*) AS n FROM jy_login_attempts WHERE fingerprint=%s AND attempted_at>now()-interval '15 minutes'", (fingerprint,)).fetchone()['n']
            if attempts >= 8:
                fail(429, '尝试次数过多，请15分钟后重试')
            user = con.execute('SELECT * FROM jy_users WHERE username=%s', (username,)).fetchone()
            try:
                verified = user and user['enabled'] and PASSWORDS.verify(user['password_hash'], password)
            except (VerificationError, InvalidHashError):
                verified = False
            if not verified:
                con.execute('INSERT INTO jy_login_attempts(fingerprint) VALUES(%s)', (fingerprint,))
                audit(con, {'username': username}, 'auth.failed')
                # Return instead of raising so failed attempts are committed.
                return JSONResponse({'error': '用户名或密码不正确'}, 401)
            token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
            expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)
            con.execute('DELETE FROM jy_sessions WHERE expires_at<now()')
            con.execute('INSERT INTO jy_sessions VALUES(%s,%s,%s,%s)', (token_hash(token), user['id'], csrf, expires))
            con.execute('UPDATE jy_users SET last_login_at=now() WHERE id=%s', (user['id'],))
            con.execute('DELETE FROM jy_login_attempts WHERE fingerprint=%s', (fingerprint,))
            audit(con, user, 'auth.login')
            result = user_public(con, user)
        from fastapi.encoders import jsonable_encoder
        response = JSONResponse(jsonable_encoder({'user': result, 'csrf': csrf}))
        response.set_cookie('jy_session', token, max_age=8*3600, httponly=True, secure=cfg.secure_cookie, samesite='strict', path='/')
        return response

    @app.get('/api/auth/me')
    def me(request: Request):
        with store.connect() as con:
            user, session = current_user(request, con, True)
            teams = con.execute('SELECT id,values_json FROM jy_records WHERE table_id=9 ORDER BY values_json->>2').fetchall()
            teams = [{'id': str(t['id']), 'name': str(t['values_json'][2]).strip(), 'department': str(t['values_json'][1]).strip()} for t in teams if is_admin(con, user) or
                     (str(t['id']) in user['team_ids'] or 'all' in scopes(con, user, 1, 'draft_edit') or
                      'all' in scopes(con,user,8,'create') or 'all' in scopes(con,user,8,'scan_correct'))]
            return {'user': user_public(con, user), 'csrf': session['csrf'], 'teams': teams, 'catalog': CATALOG, 'actions': ACTIONS}

    @app.post('/api/auth/logout')
    def logout(request: Request):
        with store.connect(write=True) as con:
            user, session = current_user(request, con, True)
            con.execute('DELETE FROM jy_sessions WHERE token_hash=%s', (session['token_hash'],))
            audit(con, user, 'auth.logout')
        response = JSONResponse({'ok': True})
        response.delete_cookie('jy_session', path='/')
        return response

    @app.post('/api/auth/password')
    async def password(request: Request):
        data = await body(request)
        new = data.get('newPassword'); validate_password(new)
        with store.connect(write=True) as con:
            user, session = current_user(request, con, True)
            try:
                valid = PASSWORDS.verify(user['password_hash'], data.get('oldPassword', ''))
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid:
                fail(400, '原密码不正确')
            if data.get('oldPassword') == new:
                fail(400, '新密码不能与原密码相同')
            con.execute('UPDATE jy_users SET password_hash=%s,must_change_password=false,version=version+1 WHERE id=%s', (PASSWORDS.hash(new), user['id']))
            con.execute('DELETE FROM jy_sessions WHERE user_id=%s AND token_hash<>%s', (user['id'], session['token_hash']))
            audit(con, user, 'auth.password_changed')
        return {'ok': True}

    @app.get('/api/admin/users')
    def users(request: Request):
        with store.connect() as con:
            user, _ = current_user(request, con); administrator(con, user)
            return {'users': [user_public(con, row) for row in con.execute('SELECT * FROM jy_users ORDER BY created_at').fetchall()]}

    @app.post('/api/admin/users')
    async def save_user(request: Request):
        data = await body(request)
        with store.connect(write=True) as con:
            actor, _ = current_user(request, con); administrator(con, actor)
            old = con.execute('SELECT * FROM jy_users WHERE id=%s', (uid(data['id']),)).fetchone() if data.get('id') else None
            if data.get('id') and not old:
                fail(404, '用户不存在')
            if old and data.get('version') != old['version']:
                fail(409, '用户资料已改变，请刷新')
            username = text(data.get('username'), '账号', 100)
            if not re.fullmatch(r'[A-Za-z0-9_.@-]{2,100}', username):
                fail(400, '账号请使用2至100位字母、数字或_.@-')
            name = text(data.get('name'), '姓名')
            department = text(data.get('department', ''), '部门', blank=True)
            if not isinstance(data.get('roleIds', []),list) or not isinstance(data.get('teamIds', []),list):
                fail(400,'角色及班组必须是列表')
            role_ids = [uid(x) for x in data.get('roleIds', [])]
            team_ids = [uid(x) for x in data.get('teamIds', [])]
            if len(set(role_ids)) != len(role_ids) or len(set(team_ids)) != len(team_ids):
                fail(400, '角色或班组重复')
            if len(con.execute('SELECT id FROM jy_roles WHERE id=ANY(%s::uuid[])', (role_ids,)).fetchall()) != len(role_ids):
                fail(400, '角色不存在')
            if len(con.execute('SELECT id FROM jy_records WHERE table_id=9 AND id=ANY(%s::uuid[])', (team_ids,)).fetchall()) != len(team_ids):
                fail(400, '班组不存在')
            enabled = data.get('enabled', True)
            if type(enabled) is not bool:
                fail(400, '启用状态无效')
            password = data.get('password')
            if not old or password:
                validate_password(password)
            account_id = str(old['id']) if old else str(uuid.uuid4())
            before = {k: old[k] for k in ['username', 'name', 'enabled', 'role_ids', 'team_ids', 'department']} if old else None
            if old:
                con.execute('UPDATE jy_users SET username=%s,name=%s,department=%s,team_ids=%s,role_ids=%s,enabled=%s,version=version+1 WHERE id=%s',
                            (username, name, department, Jsonb(team_ids), Jsonb(role_ids), enabled, account_id))
                if password:
                    con.execute('UPDATE jy_users SET password_hash=%s,must_change_password=true WHERE id=%s', (PASSWORDS.hash(password), account_id))
                if password or not enabled:
                    con.execute('DELETE FROM jy_sessions WHERE user_id=%s', (account_id,))
            else:
                con.execute('INSERT INTO jy_users(id,username,name,department,team_ids,role_ids,password_hash,enabled) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                            (account_id, username, name, department, Jsonb(team_ids), Jsonb(role_ids), PASSWORDS.hash(password), enabled))
            ensure_last_admin(con)
            audit(con, actor, 'user.update' if old else 'user.create', record_id=account_id, before=before,
                  after={'username': username, 'name': name, 'enabled': enabled, 'roleIds': role_ids, 'teamIds': team_ids, 'passwordReset': bool(password)})
        return {'id': account_id}

    @app.get('/api/admin/roles')
    def roles(request: Request):
        with store.connect() as con:
            user, _ = current_user(request, con); administrator(con, user)
            return {'roles': con.execute('SELECT * FROM jy_roles ORDER BY system_admin DESC,name').fetchall(), 'catalog': CATALOG, 'actions': ACTIONS}

    @app.post('/api/admin/roles')
    async def save_role(request: Request):
        data = await body(request)
        with store.connect(write=True) as con:
            actor, _ = current_user(request, con); administrator(con, actor)
            old = con.execute('SELECT * FROM jy_roles WHERE id=%s', (uid(data['id']),)).fetchone() if data.get('id') else None
            if data.get('id') and not old:
                fail(404, '角色不存在')
            if old and old['system_admin']:
                fail(403, '内置系统管理员角色不可修改')
            if old and data.get('version') != old['version']:
                fail(409, '角色已改变，请刷新')
            permissions = data.get('permissions', {})
            if not isinstance(permissions, dict):
                fail(400, '权限格式无效')
            for table, grant in permissions.items():
                if table not in [str(t) for t in BUSINESS_TABLES+[7,11]] or not isinstance(grant, dict):
                    fail(400, '权限表无效')
                actions = grant.get('actions', [])
                if not isinstance(actions, list) or any(a not in ACTIONS for a in actions) or grant.get('scope') not in ['own', 'teams', 'department', 'all']:
                    fail(400, '权限动作或范围无效')
                if actions and 'view' not in actions:
                    fail(400, '其他权限必须先允许查看')
            role_id = str(old['id']) if old else str(uuid.uuid4())
            name = text(data.get('name'), '角色名称')
            description = text(data.get('description', ''), '角色描述', 1000, True)
            if old:
                con.execute('UPDATE jy_roles SET name=%s,description=%s,permissions=%s,version=version+1 WHERE id=%s', (name, description, Jsonb(permissions), role_id))
            else:
                con.execute('INSERT INTO jy_roles(id,name,description,permissions) VALUES(%s,%s,%s,%s)', (role_id, name, description, Jsonb(permissions)))
            audit(con, actor, 'role.update' if old else 'role.create', record_id=role_id,
                  before=old['permissions'] if old else None, after={'name': name, 'permissions': permissions})
        return {'id': role_id}

    @app.get('/api/admin/audit')
    def audit_list(request: Request, before: int = 0, actor: str = '', action: str = '', table: int = -1, date_from: str = '', date_to: str = ''):
        with store.connect() as con:
            user, _ = current_user(request, con); administrator(con, user)
            conditions, args = ['true'], []
            if before > 0: conditions.append('id<%s'); args.append(before)
            if actor: conditions.append('actor_name=%s'); args.append(actor)
            if action: conditions.append('action=%s'); args.append(action)
            if table >= 0: conditions.append('table_id=%s'); args.append(table)
            if date_from:
                try: start=dt.datetime.combine(dt.date.fromisoformat(date_from),dt.time(),UTC7)
                except ValueError: fail(400,'开始日期无效')
                conditions.append('created_at>=%s');args.append(start)
            if date_to:
                try: end=dt.datetime.combine(dt.date.fromisoformat(date_to)+dt.timedelta(days=1),dt.time(),UTC7)
                except ValueError: fail(400,'结束日期无效')
                conditions.append('created_at<%s');args.append(end)
            rows = con.execute('SELECT * FROM jy_audit WHERE ' + ' AND '.join(conditions) + ' ORDER BY id DESC LIMIT 100', args).fetchall()
            return {'entries': rows, 'next': rows[-1]['id'] if len(rows) == 100 else None}

    @app.get('/api/tables/{table}')
    def read_table(table: int, request: Request, offset: int = 0, limit: int = 1000):
        if table not in BUSINESS_TABLES or offset < 0 or not 1 <= limit <= 2000:
            fail(400, '查询参数无效')
        with store.connect() as con:
            user, _ = current_user(request, con)
            rows = visible_rows(con, user, table)
            return {'records': [public_record(r) for r in rows[offset:offset+limit]],
                    'next': offset+limit if offset+limit < len(rows) else None}

    @app.post('/api/sync')
    async def sync(request: Request):
        data = await body(request)
        changes = data.get('changes')
        if not isinstance(changes, list) or len(changes) > 50000:
            fail(400, '变更数量无效')
        with store.connect(write=True) as con:
            user, _ = current_user(request, con)
            request_id = uid(data['requestId']) if data.get('requestId') else None
            signature = hashlib.sha256(canonical(data).encode()).hexdigest()
            prior = con.execute('SELECT * FROM jy_requests WHERE id=%s', (request_id,)).fetchone() if request_id else None
            if prior:
                if str(prior['actor_id']) != str(user['id']) or prior['signature'] != signature:
                    fail(409, '保存请求标识已使用')
                for record in prior['response_json']['records']:
                    if not record.get('deleted'):
                        current = record_by_id(con, record['id'], record['table'])
                        require(con, user, record['table'], 'view', current)
                return prior['response_json']
            output, seen, related = [], set(), set()
            for change in changes:
                if not isinstance(change, dict) or type(change.get('table')) is not int:
                    fail(400, '变更格式无效')
                table = change['table']
                if table not in BUSINESS_TABLES:
                    fail(400, '不可直接修改此表')
                record_id = uid(change['id'])
                if record_id in seen: fail(400, '变更记录重复')
                seen.add(record_id)
                old = con.execute('SELECT * FROM jy_records WHERE id=%s', (record_id,)).fetchone()
                if old and old['table_id'] != table:
                    fail(403, '记录不属于此表')
                action = 'delete' if change.get('delete') is True else 'update' if old else 'create'
                require(con, user, table, action, old)
                if data.get('import'):
                    require(con, user, table, 'import', old)
                if old and change.get('version') != old['version']:
                    fail(409, '记录已被他人修改，请刷新后重新编辑')
                if not old and change.get('version') not in (None, 0):
                    fail(409, '记录已被删除，请刷新')
                if old and table==10 and old['meta'].get('priceStatus')=='已审核':fail(403,'已审核单价不可修改或删除，请先反审')
                if old and table == 8 and old['meta'].get('submittedAt'):
                    fail(403, '已提交扫码记录不可修改或删除')
                if action == 'delete':
                    if not old: fail(409, '记录已被删除')
                    if table == 1:
                        from .work_history import unlink_work_history
                        sale_id = unlink_work_history(con, user, old)
                        if sale_id: related.add(sale_id)
                    if table == 9:
                        used = con.execute('SELECT 1 FROM jy_records WHERE team_id=%s LIMIT 1', (record_id,)).fetchone()
                        assigned = con.execute('SELECT 1 FROM jy_users WHERE team_ids ? %s LIMIT 1', (record_id,)).fetchone()
                        if used or assigned: fail(409, '班组已有业务记录或分配用户，不能删除')
                    con.execute('DELETE FROM jy_records WHERE id=%s', (record_id,))
                    audit(con, user, 'record.delete', table, record_id, before=public_record(old))
                    output.append({'id': record_id, 'deleted': True}); continue
                values = validate_values(table, change.get('values'))
                if table==9: values[2]=str(values[2]).strip()
                if table==0 and not old and not str(values[21]).strip():
                    fail(400,'新增销售订单必须包含订单子表ID')
                information = normalize_information(change.get('information', '')) if table in (0,1) else ''
                meta = change.get('meta', {}) if table == 8 else old['meta'] if old else {}
                if table == 1: meta={**meta,**work_state(values,meta.get('workStatus'))}
                if table == 8:
                    if not isinstance(meta, dict) or set(meta)-{'unit','reviewStatus','submittedAt'} or meta.get('submittedAt') != (old['meta'].get('submittedAt') if old else None):
                        fail(403, '提交回执仅由后台维护')
                    if meta.get('reviewStatus', '草稿') not in ['草稿','已确认'] or not isinstance(meta.get('unit', ''), str) or len(meta.get('unit', '')) > 80:
                        fail(400, '扫码状态或单位无效')
                    meta={**(old['meta'] if old else {}),**meta}
                    if number(values[8]) < 0: fail(400, '扫码数量不能为负数')
                if old:
                    locked = {0:[0,21,26], 1:[0,1,10,12,13,14], 2:[12], 4:[10,12,13],10:[0], 5:[2], 6:[0]}.get(table, [])
                    if any(str(values[i]) != str(old['values_json'][i]) for i in locked):
                        fail(403, '系统字段必须通过相应业务动作维护')
                elif table == 0 and str(values[26]).strip():
                    fail(403, '工单已打印数由工单确认自动维护')
                if table == 5:
                    require(con, user, 5, 'inventory_adjust', old)
                if table == 9 and any(str(r['values_json'][2]).strip() == str(values[2]).strip() and str(r['id']) != record_id for r in con.execute('SELECT id,values_json FROM jy_records WHERE table_id=9').fetchall()):
                    fail(409, '生产班组名称不能重复')
                team = resolve_team(con, user, table, values, action, old)
                from .business_rules import attendance,production,price
                try:
                    if table==2:values=production(values)
                    if table==4:
                        master=con.execute('SELECT values_json FROM jy_records WHERE id=%s',(team,)).fetchone() if team else None
                        if not master or not str(master['values_json'][1]).strip():fail(400,'请先维护生产班组的部门')
                        values=attendance(values,record_id,user['username'],prior=old['values_json'] if old else None,department=master['values_json'][1])
                    if table==10:
                        values,price_key=price(values,record_id);meta={**meta,'priceKey':price_key,'priceStatus':old['meta'].get('priceStatus','未审核') if old else '未审核'}
                except ValueError as error:fail(400,str(error))

                if not old:
                    require(con,user,table,'create',{'owner_id':user['id'],'department':user['department'],'team_id':team})
                if old:
                    con.execute('UPDATE jy_records SET values_json=%s,information=%s,meta=%s,team_id=%s,version=version+1,updated_at=now() WHERE id=%s',
                                (Jsonb(values), information, Jsonb(meta), team, record_id))
                    audit(con, user, 'record.update', table, record_id, before=public_record(old), after={'values': values, 'information': information, 'meta': meta})
                else:
                    insert_record(con, user, table, values, information, meta, team, record_id=record_id)
                output.append(public_record(record_by_id(con, record_id)))
            for sale_id in sorted(related):
                sale = record_by_id(con, sale_id, 0)
                if in_scope(user, sale, scopes(con,user,0,'view')):
                    output = [r for r in output if r['id'] != sale_id]
                    output.append(public_record(sale))
            result = {'records': output}
            if request_id:
                con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)', (request_id, user['id'], signature, Jsonb(result)))
            return result

    # Dedicated transactional workflow routes are registered separately.
    from .workflows import register_workflows
    register_workflows(app, store)
    from .business_workflows import register_business_workflows
    register_business_workflows(app,store)

    @app.get('/runtime-config.js')
    def runtime_config():
        return Response('window.JY_ENTERPRISE_MODE=true;window.JY_ENTERPRISE_API="";window.JY_RUNTIME_READY=true;', media_type='application/javascript')

    @app.get('/{path:path}')
    def static(path: str):
        path = path or 'index.html'
        file = (cfg.static_root / path).resolve()
        extensions = {'.js', '.css', '.svg', '.png', '.ico', '.webmanifest', '.html'}
        if not file.is_relative_to(cfg.static_root.resolve()) or file.suffix not in extensions or path.startswith(('enterprise/', 'backend/')) or not file.is_file():
            fail(404, '资源不存在')
        return FileResponse(file)

    return app
