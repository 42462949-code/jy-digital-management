"""PostgreSQL persistence. Every business write and its audit entry share a transaction."""
import contextlib
import datetime as dt
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from argon2 import PasswordHasher

CATALOG = json.loads(Path(__file__).with_name('catalog.json').read_text())
ACTIONS = ['view', 'create', 'update', 'delete', 'import', 'export', 'label_print',
           'report_print', 'close_order', 'reopen_order', 'generate_work', 'generate_report',
           'draft_edit', 'confirm_work', 'scan_submit', 'scan_correct', 'inventory_adjust']
PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
BUSINESS_TABLES = [0, 1, 2, 4, 5, 6, 8, 9]
TEAM_COLUMN = {1: 1, 2: 4, 4: 1, 8: 3}
UTC7 = dt.timezone(dt.timedelta(hours=7))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS jy_document_sequences (day text PRIMARY KEY, last_value bigint NOT NULL CHECK (last_value>0));
CREATE TABLE IF NOT EXISTS jy_roles (
 id uuid PRIMARY KEY, name text UNIQUE NOT NULL, description text NOT NULL DEFAULT '',
 permissions jsonb NOT NULL DEFAULT '{}', system_admin boolean NOT NULL DEFAULT false,
 version integer NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS jy_users (
 id uuid PRIMARY KEY, username text UNIQUE NOT NULL, name text NOT NULL,
 department text NOT NULL DEFAULT '', team_ids jsonb NOT NULL DEFAULT '[]',
 role_ids jsonb NOT NULL DEFAULT '[]', password_hash text NOT NULL, enabled boolean NOT NULL DEFAULT true,
 must_change_password boolean NOT NULL DEFAULT true, version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), last_login_at timestamptz);
CREATE TABLE IF NOT EXISTS jy_sessions (
 token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES jy_users(id),
 csrf text NOT NULL, expires_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS jy_records (
 id uuid PRIMARY KEY, table_id integer NOT NULL, values_json jsonb NOT NULL,
 information text NOT NULL DEFAULT '', meta jsonb NOT NULL DEFAULT '{}',
 owner_id uuid NOT NULL REFERENCES jy_users(id), department text NOT NULL DEFAULT '',
 team_id uuid, version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS jy_records_table ON jy_records(table_id,created_at,id);
CREATE INDEX IF NOT EXISTS jy_records_owner ON jy_records(table_id,owner_id);
CREATE INDEX IF NOT EXISTS jy_records_team ON jy_records(table_id,team_id);
CREATE UNIQUE INDEX IF NOT EXISTS jy_sales_source_unique ON jy_records ((btrim(values_json->>21)))
 WHERE table_id=0 AND btrim(values_json->>21)<>'';
CREATE TABLE IF NOT EXISTS jy_drafts (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES jy_users(id), team_id uuid,
 payload jsonb NOT NULL, version integer NOT NULL DEFAULT 1,
 printed_version integer, completed_at timestamptz, committed_ids jsonb,
 updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jy_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, actor_id uuid,
 actor_name text NOT NULL, action text NOT NULL, table_id integer,
 record_id text, before_json jsonb, after_json jsonb, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jy_login_attempts (
 fingerprint text NOT NULL, attempted_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS jy_login_recent ON jy_login_attempts(fingerprint,attempted_at);
CREATE TABLE IF NOT EXISTS jy_migrations (
 id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES jy_users(id),
 source_label text NOT NULL, digest text NOT NULL UNIQUE, counts jsonb NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jy_requests (
 id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES jy_users(id),
 signature text NOT NULL, response_json jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jy_label_jobs (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES jy_users(id),
 table_id integer NOT NULL, snapshot jsonb NOT NULL,
 consumed_at timestamptz, result jsonb, created_at timestamptz NOT NULL DEFAULT now());
'''


class Store:
    def __init__(self, url):
        self.url = url

    @contextlib.contextmanager
    def connect(self, write=False):
        with psycopg.connect(self.url, row_factory=dict_row) as con:
            if write:
                # Serialize write decisions, including last-admin and scope checks.
                con.execute('SELECT pg_advisory_xact_lock(641028109)')
            yield con

    def initialize(self):
        with self.connect(write=True) as con:
            con.execute(SCHEMA)
            con.execute("UPDATE jy_records SET values_json=values_json || '[\"\",\"\"]'::jsonb WHERE table_id=8 AND jsonb_array_length(values_json)=10")
            con.execute("UPDATE jy_records SET values_json=values_json || jsonb_build_array(COALESCE(meta->>'documentNo','')) WHERE table_id=1 AND jsonb_array_length(values_json)=14")
            if not con.execute('SELECT 1 FROM jy_roles LIMIT 1').fetchone():
                for name, description, permissions, admin in role_templates():
                    con.execute('INSERT INTO jy_roles(id,name,description,permissions,system_admin) VALUES(%s,%s,%s,%s,%s)',
                                (uuid.uuid4(), name, description, Jsonb(permissions), admin))

    def bootstrap(self, username, password, name='系统管理员'):
        validate_password(password)
        with self.connect(write=True) as con:
            if con.execute('SELECT 1 FROM jy_users LIMIT 1').fetchone():
                raise ValueError('管理员已初始化，不能重复创建初始账号')
            role = con.execute('SELECT id FROM jy_roles WHERE system_admin=true').fetchone()
            uid = uuid.uuid4()
            con.execute('INSERT INTO jy_users(id,username,name,password_hash,role_ids,must_change_password) VALUES(%s,%s,%s,%s,%s,true)',
                        (uid, username, name, PASSWORDS.hash(password), Jsonb([str(role['id'])])))
            audit(con, {'id': uid, 'username': username}, 'user.bootstrap', record_id=str(uid), after={'username': username})
            return str(uid)


def validate_password(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise ValueError('密码长度须为10至128个字符')


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(con, actor, action, table=None, record_id=None, before=None, after=None):
    con.execute('INSERT INTO jy_audit(actor_id,actor_name,action,table_id,record_id,before_json,after_json) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (actor.get('id'), actor.get('username', 'anonymous'), action, table, record_id,
                 Jsonb(before) if before is not None else None, Jsonb(after) if after is not None else None))


def role_templates():
    def grants(tables, actions, scope='all'):
        return {str(t): {'actions': actions, 'scope': scope} for t in tables}
    yield '系统管理员', '管理账号、角色及系统；保留至少一位启用管理员', {}, True
    sales = grants([0], ['view', 'create', 'update', 'import', 'label_print', 'close_order', 'reopen_order'])
    yield '销售人员', '销售订单维护与标签打印', sales, False
    planner = grants([0], ['view', 'generate_work'])
    planner.update(grants([1], ['view', 'draft_edit', 'confirm_work', 'report_print', 'label_print', 'generate_report']))
    planner.update(grants([9], ['view', 'create', 'update', 'delete']))
    planner.update(grants([2, 7], ['view']))
    yield '生管计划员', '下达、打印及确认工单；维护班组', planner, False
    reporter = grants([1], ['view', 'label_print'], 'teams')
    reporter.update(grants([8], ['view', 'create', 'update', 'delete', 'scan_submit'], 'own'))
    yield '班组报工员', '本班组工单与本人报工', reporter, False
    yield '仓库人员', '库存及出入库维护', grants([5, 6], ['view', 'create', 'update', 'import', 'inventory_adjust']), False
    yield '人事人员', '考勤资料维护', grants([4], ['view', 'create', 'update', 'delete', 'import', 'export']), False
    yield '管理只读', '查看业务表与看板，导出另行授权', grants([0, 1, 2, 5, 6, 7, 9], ['view']), False


def role_rows(con, user):
    ids = user['role_ids']
    return con.execute('SELECT * FROM jy_roles WHERE id=ANY(%s::uuid[])', (ids,)).fetchall() if ids else []


def is_admin(con, user):
    return any(role['system_admin'] for role in role_rows(con, user))


def scopes(con, user, table, action):
    roles = role_rows(con, user)
    if any(role['system_admin'] for role in roles):
        return {'all'}
    output = set()
    for role in roles:
        grant = role['permissions'].get(str(table), {})
        actions = grant.get('actions', [])
        if action in actions and 'view' in actions:
            output.add(grant.get('scope', 'own'))
    return output


def in_scope(user, record, allowed):
    return ('all' in allowed or
            ('own' in allowed and str(record['owner_id']) == str(user['id'])) or
            ('teams' in allowed and str(record.get('team_id')) in user['team_ids']) or
            ('department' in allowed and user['department'] and record.get('department') == user['department']))


def public_record(record):
    return {'id': str(record['id']), 'table': record['table_id'], 'version': record['version'],
            'values': record['values_json'], 'information': record['information'], 'meta': record['meta'],
            'ownerId': str(record['owner_id']), 'teamId': str(record['team_id']) if record['team_id'] else None}


def effective_permissions(con, user):
    return {str(t): {action: sorted(scopes(con, user, t, action)) for action in ACTIONS}
            for t in BUSINESS_TABLES + [7]}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
