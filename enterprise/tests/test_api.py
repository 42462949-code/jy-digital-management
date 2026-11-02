import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from enterprise.api import Config, create_app
from enterprise.db import Store


@pytest.fixture
def setup():
    url = os.environ['JY_TEST_DATABASE_URL']
    store = Store(url)
    store.initialize()
    with store.connect(write=True) as con:
        con.execute("ALTER SEQUENCE jy_price_row_no RESTART WITH 1");con.execute("ALTER SEQUENCE jy_access_row_no RESTART WITH 1")
        con.execute('TRUNCATE jy_daily_business_snapshot,jy_business_settings,jy_audit,jy_sessions,jy_records,jy_drafts,jy_migrations,jy_users,jy_roles,jy_login_attempts RESTART IDENTITY CASCADE')
    store.initialize()
    store.bootstrap('admin', 'Initial-test-password')
    app = create_app(Config(url, 'http://testserver', False))
    with TestClient(app) as admin:
        login(admin, 'admin', 'Initial-test-password', change=True)
        yield app, admin, store


def login(client, username, password='Initial-test-password', change=False):
    client.headers['Origin'] = 'http://testserver'
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf']
    if change:
        response = client.post('/api/auth/password', json={'oldPassword': password, 'newPassword': 'Changed-test-password'})
        assert response.status_code == 200, response.text
    return client


def roles(admin):
    return {row['name']: row for row in admin.get('/api/admin/roles').json()['roles']}


def user(admin, username, role_ids, teams=None):
    response = admin.post('/api/admin/users', json={'username': username, 'name': username, 'password': 'Initial-test-password', 'roleIds': role_ids, 'teamIds': teams or [], 'enabled': True})
    assert response.status_code == 200, response.text
    return response.json()['id']


def create(admin, table, values, **extra):
    record_id = str(uuid.uuid4())
    response = admin.post('/api/sync', json={'requestId': str(uuid.uuid4()), 'changes': [{'id': record_id, 'table': table, 'version': 0, 'values': values, **extra}]})
    assert response.status_code == 200, response.text
    return response.json()['records'][0]


def sale_values(order_id='SALE-1', quantity='100'):
    values = ['']*27
    values[0] = '审核'; values[4] = '客户'; values[5] = 'SO-1'; values[10] = '产品'; values[14] = quantity; values[16] = quantity; values[21] = order_id
    return values


def test_authentication_csrf_and_last_admin(setup):
    app, admin, _ = setup
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/tables/0').status_code == 401
        assert anonymous.get('/published-data-20261029-v2.json.gz').status_code == 404
        assert anonymous.get('/enterprise/db.py').status_code == 404
    old = admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/sync', json={'changes': []}).status_code == 403
    admin.headers['X-CSRF-Token'] = old
    current = admin.get('/api/admin/users').json()['users'][0]
    response = admin.post('/api/admin/users', json={'id': current['id'], 'version': current['version'], 'username':'admin', 'name':'admin', 'roleIds':current['role_ids'], 'teamIds':[], 'enabled':False})
    assert response.status_code == 409
    assert admin.get('/api/auth/me').status_code == 200


def test_role_matrix_is_server_enforced_and_revocation_is_immediate(setup):
    app, admin, _ = setup
    role = roles(admin)['管理只读']
    user(admin, 'reader', [str(role['id'])])
    record = create(admin, 0, sale_values())
    with TestClient(app) as reader:
        login(reader, 'reader', change=True)
        assert reader.get('/api/tables/0').status_code == 200
        change = {'id':record['id'], 'table':0, 'version':record['version'], 'values':record['values']}
        change['values'][4] = '越权修改'
        assert reader.post('/api/sync', json={'changes':[change]}).status_code == 403
        assert reader.post('/api/tables/0/authorize', json={'action':'export'}).status_code == 403
        assert reader.get('/api/admin/users').status_code == 403
        assert reader.get('/api/tables/4').status_code == 403
        response=admin.post('/api/admin/roles', json={'id':str(role['id']), 'version':role['version'], 'name':role['name'], 'description':role['description'], 'permissions':{}})
        assert response.status_code == 200
        assert reader.get('/api/tables/0').status_code == 403


def test_scope_batch_atomicity_and_concurrent_edits(setup):
    app, admin, _ = setup
    role_response=admin.post('/api/admin/roles',json={'name':'本人销售','permissions':{'0':{'actions':['view','create','update','delete'],'scope':'own'}}})
    assert role_response.status_code==200
    user(admin,'sales',[role_response.json()['id']])
    protected=create(admin,0,sale_values('ADMIN'))
    with TestClient(app) as sales:
        login(sales,'sales',change=True)
        own=create(sales,0,sale_values('OWN'))
        assert [r['id'] for r in sales.get('/api/tables/0').json()['records']]==[own['id']]
        changed=own['values'].copy();changed[4]='合法'
        response=sales.post('/api/sync',json={'changes':[{'id':own['id'],'table':0,'version':1,'values':changed},{'id':protected['id'],'table':0,'version':1,'delete':True}]})
        assert response.status_code==403
        assert sales.get('/api/tables/0').json()['records'][0]['values'][4]=='客户'
        payload={'changes':[{'id':own['id'],'table':0,'version':1,'values':changed}]}
        assert sales.post('/api/sync',json=payload).status_code==200
        assert sales.post('/api/sync',json=payload).status_code==409


def test_partial_work_confirmation_transaction_and_separate_batch_metadata(setup):
    app, admin, store=setup
    team=create(admin,9,['1','生产','1#','','',''])
    sale=create(admin,0,sale_values())
    def draft():
        response=admin.post('/api/work-drafts',json={'ids':[sale['id']],'type':'贴合','teamId':team['id']})
        assert response.status_code==200,response.text
        return response.json()['draft']
    first=draft();assert first['rows'][0]['values'][9]=='100'
    first['rows'][0]['values'][9]='40';first['rows'][0]['values'][0]='2、20、1#'
    saved=admin.post('/api/work-drafts/'+first['serverId']+'/save',json={'version':first['serverVersion'],'draft':first}).json()['draft']
    assert admin.post('/api/work-drafts/'+first['serverId']+'/confirm',json={'version':saved['serverVersion']}).status_code==409
    assert admin.post('/api/work-drafts/'+first['serverId']+'/print',json={'version':saved['serverVersion']}).status_code==200
    route='/api/work-drafts/'+first['serverId']+'/confirm'
    confirmed=admin.post(route,json={'version':saved['serverVersion']});assert confirmed.status_code==200,confirmed.text
    assert admin.post(route,json={'version':saved['serverVersion']}).json()['alreadyConfirmed']
    second=draft();assert second['rows'][0]['values'][9]=='60'
    second['rows'][0]['values'][0]='3'
    saved=admin.post('/api/work-drafts/'+second['serverId']+'/save',json={'version':second['serverVersion'],'draft':second}).json()['draft']
    assert admin.post('/api/work-drafts/'+second['serverId']+'/print',json={'version':saved['serverVersion']}).status_code==200
    assert admin.post('/api/work-drafts/'+second['serverId']+'/confirm',json={'version':saved['serverVersion']}).status_code==200
    works=admin.get('/api/tables/1').json()['records'];assert len(works)==2
    assert {r['information'] for r in works}=={'2\\20\\1#','3'}
    assert {r['values'][12] for r in works}=={'SALE-1'}
    sale_after=admin.get('/api/tables/0').json()['records'][0]
    assert len(sale_after['values'][26].splitlines())==2
    assert admin.post('/api/work-drafts',json={'ids':[sale['id']],'type':'贴合','teamId':team['id']}).status_code==409


def test_scan_submission_locks_server_records_and_audit_has_no_passwords(setup):
    app,admin,_=setup
    team=create(admin,9,['1','生产','1#','','',''])
    scan=create(admin,8,['2026-10-31 12:00:00','2026-10-31','贴合','1#','客户','PO','产品','54','20',''],meta={'unit':'Y','reviewStatus':'草稿','submittedAt':None})
    assert admin.post('/api/scan/submit',json={'ids':[scan['id']]}).status_code==200
    changed=scan['values'].copy();changed[8]='99'
    assert admin.post('/api/sync',json={'changes':[{'id':scan['id'],'table':8,'version':2,'values':changed,'meta':scan['meta']}]}).status_code==403
    assert admin.post('/api/sync',json={'changes':[{'id':scan['id'],'table':8,'version':2,'delete':True}]}).status_code==403
    response=admin.get('/api/admin/audit');assert response.status_code==200
    assert 'Changed-test-password' not in response.text and 'Initial-test-password' not in response.text and 'password_hash' not in response.text


def test_migration_previews_conflicts_and_does_not_overwrite_existing_data(setup):
    _,admin,_=setup
    tables=[[] for _ in range(10)];tables[0]=[sale_values()]
    data={'tables':tables,'information':{'0':{'SALE-1':'2'}},'scanMeta':[],'sourceLabel':'指定主电脑'}
    preview=admin.post('/api/admin/migration/preview',json=data);assert preview.status_code==200
    result=preview.json();assert not result['conflicts']
    commit={'data':data,'digest':result['digest']}
    assert admin.post('/api/admin/migration/commit',json=commit).status_code==200
    assert admin.post('/api/admin/migration/commit',json=commit).json()['alreadyImported']
    tables[0].append(sale_values('OTHER'))
    result=admin.post('/api/admin/migration/preview',json=data).json()
    assert admin.post('/api/admin/migration/commit',json={'data':data,'digest':result['digest']}).status_code==409


def test_team_scope_labels_and_latest_attendance_reference(setup):
    app,admin,_=setup
    a=create(admin,9,['1','生产','1#','','',''])
    b=create(admin,9,['2','生产','2#','','',''])
    for team,source in [('1#','S1'),('2#','S2')]:
        create(admin,1,['2026/10/31',team,'客户','SO','','产品','','54','10',0,'Y','',source,'贴合'],information='2')
    reporter=roles(admin)['班组报工员']
    user(admin,'reporter',[str(reporter['id'])],[a['id']])
    with TestClient(app) as worker:
        login(worker,'reporter',change=True)
        result=worker.get('/api/tables/1');assert result.status_code==200
        assert len(result.json()['records'])==1
        assert result.json()['records'][0]['values'][1]=='1#'
        result=worker.post('/api/tables/1/authorize',json={'action':'label_print'})
        assert result.status_code==200 and len(result.json()['records'])==1
        assert worker.get('/api/references/attendance-teams').status_code==403
    hr=roles(admin)['人事人员'];user(admin,'hr',[str(hr['id'])])
    with TestClient(app) as hr_client:
        login(hr_client,'hr',change=True)
        assert hr_client.get('/api/tables/9').status_code==403
        assert hr_client.get('/api/references/attendance-teams').json()['names']==['1#','2#']
        values=b['values'].copy();values[2]='新班组'
        assert admin.post('/api/sync',json={'changes':[{'id':b['id'],'table':9,'version':1,'values':values}]}).status_code==200
        assert hr_client.get('/api/references/attendance-teams').json()['names']==['1#','新班组']


def test_label_confirmation_clears_only_snapshot_and_is_idempotent(setup):
    app,admin,_=setup
    first=create(admin,0,sale_values('A'),information='2')
    second=create(admin,0,sale_values('B'),information='3')
    role=admin.post('/api/admin/roles',json={'name':'仅标签','permissions':{'0':{'scope':'all','actions':['view','label_print']}}}).json()['id']
    user(admin,'labels',[role])
    with TestClient(app) as printer:
        login(printer,'labels',change=True)
        job=printer.post('/api/tables/0/authorize',json={'action':'label_print'}).json()['jobId']
        assert admin.post('/api/sync',json={'changes':[{'id':second['id'],'table':0,'version':1,'values':second['values'],'information':'4'}]}).status_code==200
        result=printer.post('/api/labels/jobs/'+job+'/consume',json={})
        assert result.status_code==200 and result.json()=={'cleared':1,'changed':1}
        assert printer.post('/api/labels/jobs/'+job+'/consume',json={}).json()==result.json()
        rows={r['id']:r for r in admin.get('/api/tables/0').json()['records']}
        assert rows[first['id']]['information']=='' and rows[second['id']]['information']=='4'
        assert printer.post('/api/sync',json={'changes':[{'id':second['id'],'table':0,'version':2,'values':second['values'],'information':''}]}).status_code==403


def test_planner_can_confirm_without_arbitrary_sales_edit_and_stale_draft_cannot_overissue(setup):
    app,admin,_=setup
    team=create(admin,9,['1','','1#','','','']);sale=create(admin,0,sale_values())
    role=str(roles(admin)['生管计划员']['id'])
    user(admin,'plan1',[role]);user(admin,'plan2',[role])
    with TestClient(app) as p1,TestClient(app) as p2:
        login(p1,'plan1',change=True);login(p2,'plan2',change=True)
        drafts=[]
        for client in [p1,p2]:
            response=client.post('/api/work-drafts',json={'ids':[sale['id']],'type':'贴合','teamId':team['id']})
            assert response.status_code==200,response.text
            drafts.append(response.json()['draft'])
        first=drafts[0];first['rows'][0]['values'][9]='40'
        first=p1.post('/api/work-drafts/'+first['serverId']+'/save',json={'version':first['serverVersion'],'draft':first}).json()['draft']
        for client,draft in [(p1,first),(p2,drafts[1])]:
            assert client.post('/api/work-drafts/'+draft['serverId']+'/print',json={'version':draft['serverVersion']}).status_code==200
        assert p1.post('/api/work-drafts/'+first['serverId']+'/confirm',json={'version':first['serverVersion']}).status_code==200
        assert p2.post('/api/work-drafts/'+drafts[1]['serverId']+'/confirm',json={'version':drafts[1]['serverVersion']}).status_code==409
        record=admin.get('/api/tables/0').json()['records'][0]
        assert record['values'][26].endswith('：40')
        assert p1.post('/api/sync',json={'changes':[{'id':sale['id'],'table':0,'version':record['version'],'values':record['values'],'information':'fake'}]}).status_code==403


def test_sync_retries_do_not_duplicate_and_submitted_correction_requires_separate_permission(setup):
    app,admin,_=setup
    payload={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'table':0,'version':0,'values':sale_values()}]}
    first=admin.post('/api/sync',json=payload);assert first.status_code==200
    assert admin.post('/api/sync',json=payload).json()==first.json()
    assert len(admin.get('/api/tables/0').json()['records'])==1
    team=create(admin,9,['1','','1#','','',''])
    record=create(admin,8,['2026-10-31 12:00:00','2026-10-31','贴合','1#','客户','PO','产品','54','20',''],meta={'submittedAt':None,'reviewStatus':'草稿'})
    admin.post('/api/scan/submit',json={'ids':[record['id']]})
    values=record['values'].copy();values[8]='18'
    result=admin.post('/api/scan/'+record['id']+'/correct',json={'version':2,'values':values,'reason':'核对后更正数量'})
    assert result.status_code==200,result.text
    assert result.json()['record']['meta']['submittedAt']
    assert result.json()['record']['values'][8]=='18'
    assert admin.get('/api/admin/audit?action=scan.correct').json()['entries'][0]['before_json']['values'][8]=='20'
    assert admin.post('/api/scan/'+record['id']+'/correct',json={'version':2,'values':values,'reason':'重试'}).status_code==409


def test_sales_close_reopen_restores_status_and_checks_permission(setup):
    app, admin, store = setup
    values = sale_values('REOPEN-1'); values[0] = '待审核'
    record = create(admin, 0, values)
    for _ in range(2):
        assert admin.post('/api/sales/close', json={'ids':[record['id']]}).status_code == 200
    response = admin.post('/api/sales/reopen', json={'ids':[record['id']]})
    assert response.status_code == 200, response.text
    assert response.json()['records'][0]['values'][0] == '待审核'
    legacy = sale_values('REOPEN-OLD'); legacy[0] = '关闭'
    old = create(admin, 0, legacy)
    assert admin.post('/api/sales/reopen', json={'ids':[old['id']]}).json()['records'][0]['values'][0] == '审核'
    reader = roles(admin)['管理只读']; user(admin, 'reopen-reader', [str(reader['id'])])
    with TestClient(app) as client:
        login(client, 'reopen-reader', change=True)
        assert client.post('/api/sales/reopen', json={'ids':[record['id']]}).status_code == 403
    actions = [r['action'] for r in admin.get('/api/admin/audit').json()['entries']]
    assert 'sales.reopen' in actions and 'sales.close' in actions


def test_work_deletion_removes_only_linked_history_atomically_and_idempotently(setup):
    app, admin, store = setup
    team = create(admin,9,['1','生产','DELETE#','','',''])
    sale = create(admin,0,sale_values('DELETE-SALE'))
    works=[]
    for quantity in ['40','60']:
        draft=admin.post('/api/work-drafts',json={'ids':[sale['id']],'type':'贴合','teamId':team['id']}).json()['draft']
        draft['rows'][0]['values'][9]=quantity
        draft=admin.post('/api/work-drafts/'+draft['serverId']+'/save',json={'version':draft['serverVersion'],'draft':draft}).json()['draft']
        assert admin.post('/api/work-drafts/'+draft['serverId']+'/print',json={'version':draft['serverVersion']}).status_code==200
        confirmed=admin.post('/api/work-drafts/'+draft['serverId']+'/confirm',json={'version':draft['serverVersion']})
        assert confirmed.status_code==200,confirmed.text
        works.append(confirmed.json()['ids'][0])
    records={r['id']:r for r in admin.get('/api/tables/1').json()['records']}
    before=admin.get('/api/tables/0').json()['records'][0]
    assert before['values'][26].endswith('：60')
    # A stale second deletion rolls back the first deletion and its history change.
    changes=[{'id':works[0],'table':1,'version':records[works[0]]['version'],'delete':True},{'id':works[1],'table':1,'version':999,'delete':True}]
    assert admin.post('/api/sync',json={'changes':changes}).status_code==409
    assert len(admin.get('/api/tables/1').json()['records'])==2
    assert admin.get('/api/tables/0').json()['records'][0]['values'][26]==before['values'][26]
    # Later quantity edits must still unlink the original confirmed history entry.
    changed=records[works[0]]['values'].copy();changed[8]='35'
    response=admin.post('/api/sync',json={'changes':[{'id':works[0],'table':1,'version':records[works[0]]['version'],'values':changed}]})
    assert response.status_code==200,response.text
    work=response.json()['records'][0]
    request={'requestId':str(uuid.uuid4()),'changes':[{'id':work['id'],'table':1,'version':work['version'],'delete':True}]}
    response=admin.post('/api/sync',json=request);assert response.status_code==200,response.text
    assert admin.post('/api/sync',json=request).json()==response.json()
    remaining=admin.get('/api/tables/0').json()['records'][0]
    assert remaining['values'][26].endswith('：60') and '：40' not in remaining['values'][26]
    assert any(r.get('table')==0 and r['id']==sale['id'] for r in response.json()['records'])
    audit_entries=admin.get('/api/admin/audit?action=sales.work_print_deleted').json()['entries']
    assert len(audit_entries)==1
    # Work deletion permission authorizes this system-maintained side effect;
    # users without sales-view permission receive no sales data.
    role=admin.post('/api/admin/roles',json={'name':'工单删除专员','permissions':{'1':{'scope':'all','actions':['view','delete']}}}).json()
    role_id=role.get('id') or role.get('role',{}).get('id')
    user(admin,'work-deleter',[role_id])
    with TestClient(app) as client:
        login(client,'work-deleter',change=True)
        record=client.get('/api/tables/1').json()['records'][0]
        response=client.post('/api/sync',json={'changes':[{'id':record['id'],'table':1,'version':record['version'],'delete':True}]})
        assert response.status_code==200,response.text
        assert response.json()['records']==[{'id':record['id'],'deleted':True}]
        assert client.get('/api/tables/0').status_code==403
    assert admin.get('/api/tables/0').json()['records'][0]['values'][26]==''


def test_legacy_work_history_matches_date_type_quantity_and_preserves_other_lines():
    from enterprise.work_history import remove_history_line
    values=['2026/11/1 13:26 18']+['']*13;values[8]='202.00';values[13]='贴合'
    history='贴合2026/10/31：202\n贴合+2026/11/01+202.00\n泡棉2026/11/1：202\n备注'
    assert remove_history_line(history,values)=='贴合2026/10/31：202\n泡棉2026/11/1：202\n备注'
    duplicate='贴合2026/11/1：202\n贴合2026/11/1：202'
    assert remove_history_line(duplicate,values)=='贴合2026/11/1：202'
    assert remove_history_line('备注',values)=='备注'


def test_document_number_persists_in_work_column_and_cannot_be_changed(setup):
    app,admin,store=setup
    team=create(admin,9,['1','生产','NUMBER#','','',''])
    sale=create(admin,0,sale_values('NUMBER-SALE'))
    payload={'ids':[sale['id']],'type':'贴合','teamId':team['id']}
    first=admin.post('/api/work-drafts',json=payload).json()['draft']
    import re
    assert re.fullmatch(r'MO-\d{6}-\d{2,}',first['documentNo'])
    assert first['fields'][-1]=='工单号' and first['rows'][0]['values'][15]==first['documentNo']
    assert admin.post('/api/work-drafts',json=payload).json()['draft']['documentNo']==first['documentNo']
    tampered={**first,'documentNo':'MO-000000-99'}
    assert admin.post('/api/work-drafts/'+first['serverId']+'/save',json={'version':first['serverVersion'],'draft':tampered}).status_code==403
    first['columns']=[{'n':'二维码','w':150}]
    first=admin.post('/api/work-drafts/'+first['serverId']+'/save',json={'version':first['serverVersion'],'draft':first}).json()['draft']
    assert admin.post('/api/work-drafts/'+first['serverId']+'/print',json={'version':first['serverVersion']}).status_code==200
    response=admin.post('/api/work-drafts/'+first['serverId']+'/confirm',json={'version':first['serverVersion']})
    assert response.status_code==200,response.text
    work=admin.get('/api/tables/1').json()['records'][0]
    assert len(work['values'])==15 and work['values'][14]==first['documentNo']
    changed=work['values'].copy();changed[14]='MO-000000-99'
    assert admin.post('/api/sync',json={'changes':[{'id':work['id'],'table':1,'version':work['version'],'values':changed}]}).status_code==403
    # Delete the work then create again: number allocation is never rolled back by business deletion.
    assert admin.post('/api/sync',json={'changes':[{'id':work['id'],'table':1,'version':work['version'],'delete':True}]}).status_code==200
    second=admin.post('/api/work-drafts',json=payload).json()['draft']
    assert int(second['documentNo'].split('-')[-1])==int(first['documentNo'].split('-')[-1])+1
    assert admin.post('/api/work-drafts/'+second['serverId']+'/discard',json={}).status_code==200
    third=admin.post('/api/work-drafts',json=payload).json()['draft']
    assert int(third['documentNo'].split('-')[-1])==int(second['documentNo'].split('-')[-1])+1


def test_legacy_draft_gets_one_number_and_requires_print_again(setup):
    app,admin,store=setup
    team=create(admin,9,['1','生产','OLD#','','','']);sale=create(admin,0,sale_values('OLD-NUMBER'))
    draft=admin.post('/api/work-drafts',json={'ids':[sale['id']],'type':'贴合','teamId':team['id']}).json()['draft']
    from psycopg.types.json import Jsonb
    with store.connect(write=True) as con:
        row=con.execute('SELECT * FROM jy_drafts WHERE id=%s',(draft['serverId'],)).fetchone();old=row['payload']
        old.pop('documentNo');old['fields'].pop()
        for entries in [old['rows'],old['_originalRows']]:
            for entry in entries:entry['values'].pop()
        con.execute('UPDATE jy_drafts SET payload=%s,printed_version=version WHERE id=%s',(Jsonb(old),row['id']))
    upgraded=admin.get('/api/work-drafts').json()['drafts'][0]
    assert upgraded['documentNo'] and upgraded['rows'][0]['values'][15]==upgraded['documentNo']
    assert upgraded['printedRevision']==-1
    assert admin.get('/api/work-drafts').json()['drafts'][0]['documentNo']==upgraded['documentNo']


def test_scan_work_number_and_order_id_survive_submit_and_legacy_upgrade(setup):
    app,admin,store=setup
    team=create(admin,9,['1','生产','SCAN#','','',''])
    values=['2026-11-01 12:00:00','2026-11-01','贴合','SCAN#','客户','PO','产品','58','25','备注','MO-261101-01','1000357278']
    scan=create(admin,8,values,meta={'unit':'Y','reviewStatus':'草稿','submittedAt':None})
    assert admin.post('/api/scan/submit',json={'ids':[scan['id']]}).status_code==200
    stored=admin.get('/api/tables/8').json()['records'][0]
    assert stored['values'][10:]==['MO-261101-01','1000357278'] and stored['meta']['unit']=='Y'
    changed=stored['values'].copy();changed[10]='CHANGED'
    assert admin.post('/api/sync',json={'changes':[{'id':stored['id'],'table':8,'version':stored['version'],'values':changed,'meta':stored['meta']}]}).status_code==403
    # Simulate the former ten-field storage and verify initialization keeps its receipt.
    from psycopg.types.json import Jsonb
    with store.connect(write=True) as con:
        con.execute('UPDATE jy_records SET values_json=%s WHERE id=%s',(Jsonb(values[:10]),stored['id']))
    store.initialize()
    upgraded=admin.get('/api/tables/8').json()['records'][0]
    assert upgraded['values']==values[:10]+['','']
    assert upgraded['meta']==stored['meta']


def test_confirmed_document_print_is_read_only_complete_and_permission_checked(setup):
    app,admin,store=setup
    a=create(admin,9,['1','生产','PRINT-A','','','']);b=create(admin,9,['2','生产','PRINT-B','','',''])
    def work(source,number,team):
        return create(admin,1,['2026/11/1','PRINT-'+team,'客户','SO-'+source,'PO','产品','','58','10',0,'Y','',source,'贴合',number])
    first=work('ONE','MO-261101-01','A');second=work('TWO','MO-261101-01','A');work('OTHER','MO-261101-02','A')
    role=admin.post('/api/admin/roles',json={'name':'仅打印工单','permissions':{'1':{'scope':'teams','actions':['view','report_print']}}}).json()
    role_id=role.get('id') or role.get('role',{}).get('id');user(admin,'printer',[role_id],[a['id']])
    with TestClient(app) as printer:
        login(printer,'printer',change=True)
        response=printer.post('/api/work-orders/print-document',json={'documentNo':'MO-261101-01'})
        assert response.status_code==200,response.text
        assert {r['id'] for r in response.json()['records']}=={first['id'],second['id']}
        assert printer.post('/api/sync',json={'changes':[{'id':first['id'],'table':1,'version':first['version'],'values':first['values']}]}).status_code==403
        # A single inaccessible line blocks the entire document rather than printing a partial report.
        work('HIDDEN','MO-261101-01','B')
        assert printer.post('/api/work-orders/print-document',json={'documentNo':'MO-261101-01'}).status_code==403
        assert printer.post('/api/work-orders/print-document',json={'documentNo':'MISSING'}).status_code==404
        # Removing print permission is effective again when the print button is clicked.
        stored=next(r for r in admin.get('/api/admin/roles').json()['roles'] if r['id']==role_id)
        assert admin.post('/api/admin/roles',json={'id':role_id,'version':stored['version'],'name':stored['name'],'permissions':{'1':{'scope':'teams','actions':['view']}}}).status_code==200
        assert printer.post('/api/work-orders/print-document',json={'documentNo':'MO-261101-02','phase':'print'}).status_code==403
    records=admin.get('/api/tables/1').json()['records']
    assert all(r['version']==1 and r['values'][8]=='10' for r in records)


def test_production_report_carries_document_number_and_preserves_old_fields(setup):
    app,admin,store=setup
    team=create(admin,9,['1','贴合','PROD#','','',''])
    work=create(admin,1,['2026/11/1','PROD#','客户','SO','PO','产品','','58','100',0,'Y','备注','PROD-SALE','贴合','MO-261101-01'],information='25')
    payload={'requestId':str(uuid.uuid4()),'records':[{'id':work['id'],'version':work['version'],'information':'25'}],'date':'2026-11-01','department':'贴合','teamId':team['id']}
    response=admin.post('/api/work-orders/generate-reports',json=payload)
    assert response.status_code==200,response.text
    report=admin.get('/api/tables/2').json()['records'][0]
    assert len(report['values'])==22 and report['values'][17]=='MO-261101-01'
    assert report['values'][3]=='PO' and report['values'][12]=='PROD-SALE'
    assert admin.post('/api/work-orders/generate-reports',json=payload).json()['ids']==response.json()['ids']
    from psycopg.types.json import Jsonb
    legacy=report['values'][:17];legacy[7:11]=['3','5','保留原因','原责任人']
    with store.connect(write=True) as con:
        con.execute('UPDATE jy_records SET values_json=%s WHERE id=%s',(Jsonb(legacy),report['id']))
    store.initialize()
    upgraded=admin.get('/api/tables/2').json()['records'][0]
    assert upgraded['values'][:17]==legacy and upgraded['values'][17]=='MO-261101-01'


def test_work_owing_auto_closes_exactly_and_stays_closed_without_repeat_updates(setup):
    app,admin,store=setup
    values=['2026/11/1','','客户','SO','PO','产品','','58','0.3','0.2','Y','','STATE-SALE','贴合','MO-261101-01']
    work=create(admin,1,values)
    assert work['meta']['workStatus']=='审核' and work['meta']['workOwing']=='0.1'
    values[9]='0.3'
    response=admin.post('/api/sync',json={'changes':[{'id':work['id'],'table':1,'version':work['version'],'values':values}]})
    assert response.status_code==200,response.text
    closed=response.json()['records'][0]
    assert closed['meta']['workStatus']=='关闭' and closed['meta']['workOwing']=='0'
    version=closed['version'];store.initialize();store.initialize()
    stable=admin.get('/api/tables/1').json()['records'][0]
    assert stable['version']==version
    values[9]='0.1'
    response=admin.post('/api/sync',json={'changes':[{'id':work['id'],'table':1,'version':version,'values':values,'meta':{'workStatus':'审核','workOwing':'999'}}]})
    adjusted=response.json()['records'][0]
    assert adjusted['meta']['workStatus']=='关闭' and adjusted['meta']['workOwing']=='0.2'
    assert len(adjusted['values'])==15
    from enterprise.work_state import work_state
    blank=values.copy();blank[8]='';blank[9]=''
    assert work_state(blank)=={'workStatus':'审核','workOwing':''}
    over=values.copy();over[8]='100';over[9]='120'
    assert work_state(over)=={'workStatus':'审核','workOwing':'-20'}


def test_work_manual_close_reopen_is_scoped_atomic_and_idempotent(setup):
    app,admin,store=setup
    base=['2026/11/1','','客户','SO','PO','产品','','58','100','20','Y','','CLOSE-A','贴合','MO-261101-01']
    a=create(admin,1,base);done=base.copy();done[12]='CLOSE-B';done[9]='100';b=create(admin,1,done)
    role=admin.post('/api/admin/roles',json={'name':'工单结案专员','permissions':{'1':{'scope':'all','actions':['view','close_order','reopen_order']}}}).json()
    role_id=role.get('id') or role.get('role',{}).get('id');user(admin,'work-closer',[role_id])
    with TestClient(app) as closer:
        login(closer,'work-closer',change=True)
        payload={'requestId':str(uuid.uuid4()),'reopen':False,'records':[{'id':a['id'],'version':a['version']},{'id':b['id'],'version':b['version']}]}
        response=closer.post('/api/work-orders/closure',json=payload)
        assert response.status_code==200,response.text
        closed=response.json();assert closed['changed']==1
        assert closer.post('/api/work-orders/closure',json=payload).json()==closed
        records={r['id']:r for r in closed['records']}
        assert records[a['id']]['meta']['workStatus']=='关闭' and records[b['id']]['version']==b['version']
        reopened=closer.post('/api/work-orders/closure',json={'reopen':True,'records':[{'id':r['id'],'version':r['version']} for r in records.values()]}).json()
        assert reopened['changed']==1 and reopened['skippedCompleted']==1
        records={r['id']:r for r in reopened['records']}
        assert records[a['id']]['meta']['workStatus']=='审核' and records[b['id']]['meta']['workStatus']=='关闭'
        failure=closer.post('/api/work-orders/closure',json={'reopen':False,'records':[{'id':a['id'],'version':records[a['id']]['version']},{'id':b['id'],'version':999}]})
        assert failure.status_code==409
        actual={r['id']:r for r in closer.get('/api/tables/1').json()['records']}
        assert actual[a['id']]['meta']['workStatus']=='审核'
        assert actual[a['id']]['values']==a['values'] and actual[b['id']]['values']==b['values']
        assert closer.post('/api/sync',json={'changes':[{'id':a['id'],'table':1,'version':actual[a['id']]['version'],'values':a['values']}]}).status_code==403
    entries=admin.get('/api/admin/audit?action=work.close').json()['entries']
    assert len(entries)==1


def test_scan_confirm_creates_production_exactly_once_and_checks_scope_atomically(setup):
    app,admin,store=setup
    team_a=create(admin,9,['1','生产','TRANSFER-A','','',''])
    create(admin,9,['2','生产','TRANSFER-B','','',''])
    values=['2026-11-01 10:20:30','2026-11-01','贴合','TRANSFER-A','客户','PO','产品','58','12.5','备注','MO-261101-01','TRANSFER-SALE']
    first=create(admin,8,values,meta={'unit':'Y','submittedAt':None})
    second=create(admin,8,values,meta={'unit':'Y','submittedAt':None})
    hidden=values.copy();hidden[3]='TRANSFER-B';other=create(admin,8,hidden)
    invalid=values.copy();invalid[2]=' ';bad=create(admin,8,invalid)
    assert admin.post('/api/scan/submit',json={'ids':[first['id']],'versions':{first['id']:999}}).status_code==409
    assert admin.post('/api/scan/submit',json={'ids':[first['id'],bad['id']]}).status_code==400
    assert admin.get('/api/tables/2').json()['records']==[]
    role=admin.post('/api/admin/roles',json={'name':'仅确认扫码','permissions':{'8':{'scope':'teams','actions':['view','scan_submit']}}}).json()
    role_id=role.get('id') or role.get('role',{}).get('id');user(admin,'scan-transfer',[role_id],[team_a['id']])
    with TestClient(app) as scanner:
        login(scanner,'scan-transfer',change=True)
        assert scanner.post('/api/scan/submit',json={'ids':[first['id'],other['id']]}).status_code==403
        assert admin.get('/api/tables/2').json()['records']==[]
        payload={'ids':[first['id']],'versions':{first['id']:first['version']}}
        result=scanner.post('/api/scan/submit',json=payload)
        assert result.status_code==200,result.text
        assert result.json()['acceptedIds']==[first['id']]
        assert scanner.post('/api/scan/submit',json=payload).status_code==200
        reports=admin.get('/api/tables/2').json()['records'];assert len(reports)==1
        report=reports[0]
        assert report['values']==['2026-11-01','客户','产品','','TRANSFER-A','12.5','Y','','','','','备注','TRANSFER-SALE','2026-11-01 10:20:30','','','贴合','MO-261101-01','','','','']
        assert report['meta']['sourceScanId']==first['id']
        scans={r['id']:r for r in admin.get('/api/tables/8').json()['records']}
        assert scans[first['id']]['meta']['productionReportId']==report['id']
        assert not scans[second['id']]['meta'].get('submittedAt')
        assert scanner.post('/api/sync',json={'changes':[{'id':first['id'],'table':8,'version':2,'delete':True}]}).status_code==403
        stored=next(r for r in admin.get('/api/admin/roles').json()['roles'] if r['id']==role_id)
        admin.post('/api/admin/roles',json={'id':role_id,'version':stored['version'],'name':stored['name'],'permissions':{'8':{'scope':'teams','actions':['view']}}})
        assert scanner.post('/api/scan/submit',json=payload).status_code==403
    assert len(admin.get('/api/admin/audit?action=scan.generate_report').json()['entries'])==1


def test_scanner_team_reference_includes_department_without_unassigned_team_access(setup):
    app,admin,_=setup
    assigned=create(admin,9,['1','贴合','部门联动A','','',''])
    create(admin,9,['2','泡棉','部门联动B','','',''])
    role=admin.post('/api/admin/roles',json={'name':'班组扫码员','permissions':{'8':{'scope':'teams','actions':['view','create','scan_submit']}}}).json()
    role_id=role.get('id') or role.get('role',{}).get('id');user(admin,'scan-context',[role_id],[assigned['id']])
    with TestClient(app) as scanner:
        login(scanner,'scan-context',change=True)
        assert scanner.get('/api/tables/9').status_code==403
        reference=scanner.get('/api/auth/me').json()['teams']
        assert reference==[{'id':assigned['id'],'name':'部门联动A','department':'贴合'}]
        changed=assigned['values'].copy();changed[1]='泡棉'
        assert admin.post('/api/sync',json={'changes':[{'id':assigned['id'],'table':9,'version':assigned['version'],'values':changed}]}).status_code==200
        assert scanner.get('/api/auth/me').json()['teams'][0]['department']=='泡棉'


def test_attendance_unique_identity_derived_hours_and_actor_are_authoritative(setup):
    app,admin,store=setup
    team=create(admin,9,['1','贴合','ATT-A','','',''])
    values=['2026-10-31','ATT-A','8','2','1','','','','','',str(uuid.uuid4()),'伪造部门','forged','1900-01-01']
    first=create(admin,4,values);second=create(admin,4,values)
    assert first['values'][10]==first['id'] and second['values'][10]==second['id'] and first['id']!=second['id']
    assert first['values'][5:7]==['11','13']
    assert first['values'][11]=='贴合' and first['values'][12]=='admin' and first['values'][13]!='1900-01-01'
    before=first['values'].copy();changed=before.copy();changed[2]='10';changed[6]='999'
    response=admin.post('/api/sync',json={'changes':[{'id':first['id'],'table':4,'version':first['version'],'values':changed}]})
    assert response.status_code==200,response.text
    updated=response.json()['records'][0];assert updated['values'][5:7]==['13','15'] and updated['values'][10:]==before[10:]
    assert admin.post('/api/sync',json={'changes':[{'id':first['id'],'table':4,'version':first['version'],'values':before}]}).status_code==409
    # A separate new row has its own version/identity and never overwrites another leader's entry.
    assert len(admin.get('/api/tables/4').json()['records'])==2


def test_price_review_controls_four_field_match_and_locks_approved_rows(setup):
    app,admin,_=setup
    create(admin,9,['1','贴合','PRICE-A','','',''])
    values=['','客户A','材料A','58','产品A','VND','1.25','']
    price=create(admin,10,values)
    sale=sale_values('PRICE-ID');sale[4]='客户A';sale[7]='材料A';sale[8]='PO';sale[9]='58';sale[10]='产品A';create(admin,0,sale)
    work=create(admin,1,['2026-11-01','PRICE-A','客户A','SO','PO','产品A','材料A','58','100',0,'Y','','PRICE-ID','贴合','MO-261101-01'])
    def scan(spec='58'):
        return create(admin,8,['2026-10-31 10:20:30','2026-10-31','贴合','PRICE-A','客户A','PO','产品A',spec,'4','','MO-261101-01','PRICE-ID'],meta={'unit':'wrong'})
    first=scan();assert admin.post('/api/scan/submit',json={'ids':[first['id']]}).status_code==200
    report=admin.get('/api/tables/2').json()['records'][0];assert report['values'][18:20]==['',''] and report['values'][6]=='Y'
    payload={'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':price['id'],'version':price['version']}]}
    approved=admin.post('/api/price-list/review',json=payload);assert approved.status_code==200,approved.text
    assert admin.post('/api/price-list/review',json=payload).json()==approved.json()
    current=approved.json()['records'][0];assert current['meta']['priceStatus']=='已审核'
    assert admin.post('/api/sync',json={'changes':[{'id':price['id'],'table':10,'version':current['version'],'values':price['values']}]}).status_code==403
    assert admin.post('/api/sync',json={'changes':[{'id':price['id'],'table':10,'version':current['version'],'delete':True}]}).status_code==403
    duplicate=create(admin,10,values)
    assert admin.post('/api/price-list/review',json={'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':duplicate['id'],'version':duplicate['version']}]}).status_code==409
    second=scan();assert admin.post('/api/scan/submit',json={'ids':[second['id']]}).status_code==200
    reports=admin.get('/api/tables/2').json()['records'];matched=next(r for r in reports if r['meta'].get('sourceScanId')==second['id'])
    assert matched['values'][18:]==['1.25','5','58','VND']
    stored_work=admin.get('/api/tables/1').json()['records'][0];assert stored_work['values'][9]=='8'
    assert admin.post('/api/scan/submit',json={'ids':[second['id']]}).status_code==200
    assert admin.get('/api/tables/1').json()['records'][0]['values'][9]=='8'
    # A manually filled price recomputes amount and ignores a client-forged total.
    missing=create(admin,2,['2026-10-31','无匹配客户','产品','','PRICE-A','4','Y','','','','','','','2026-10-31 10:00:00','','','贴合','','','','不同规格',''])
    v=missing['values'].copy();v[18]='0.3';v[19]='999'
    result=admin.post('/api/sync',json={'changes':[{'id':missing['id'],'table':2,'version':missing['version'],'values':v}]})
    assert result.status_code==200 and result.json()['records'][0]['values'][19]=='1.2'
    reversed=admin.post('/api/price-list/review',json={'requestId':str(uuid.uuid4()),'approve':False,'records':[{'id':price['id'],'version':current['version']}]})
    assert reversed.status_code==200 and reversed.json()['records'][0]['meta']['priceStatus']=='未审核'


def test_entered_work_quantity_reports_validate_and_commit_atomically(setup):
    app,admin,_=setup
    team=create(admin,9,['1','泡棉','MANUAL-A','','',''])
    price=create(admin,10,['','客户','MAT','58','产品','VND','0.3',''])
    admin.post('/api/price-list/review',json={'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':price['id'],'version':1}]})
    sale=sale_values('MANUAL-ID');sale[7]='MAT';sale[8]='PO';sale[9]='58';sale[10]='产品';create(admin,0,sale)
    work=create(admin,1,['2026-11-01','MANUAL-A','客户','SO','PO','产品','MAT','58','20','0','Y','','MANUAL-ID','泡棉','MO-261101-02'],information='5')
    payload={'requestId':str(uuid.uuid4()),'records':[{'id':work['id'],'version':1,'information':'5'}],'date':'2026-10-31','department':'泡棉','teamId':team['id']}
    result=admin.post('/api/work-orders/generate-reports',json=payload);assert result.status_code==200,result.text
    report=admin.get('/api/tables/2').json()['records'][0]
    assert report['values'][0]=='2026-10-31' and report['values'][4:7]==['MANUAL-A','5','Y'] and report['values'][16:] == ['泡棉','MO-261101-02','0.3','1.5','58','VND']
    row=admin.get('/api/tables/1').json()['records'][0];assert row['information']=='' and row['values'][9]=='5'
    assert admin.post('/api/work-orders/generate-reports',json=payload).json()==result.json()
    assert len(admin.get('/api/tables/2').json()['records'])==1
    missing={**payload,'requestId':str(uuid.uuid4()),'records':[{'id':work['id'],'version':row['version'],'information':''}]}
    assert admin.post('/api/work-orders/generate-reports',json=missing).status_code==400
    assert len(admin.get('/api/tables/2').json()['records'])==1


def test_hourly_output_snapshots_respect_ten_am_cutoff_and_raw_amounts(setup,monkeypatch):
    import datetime as dt
    import enterprise.business_workflows as workflow
    app,admin,_=setup
    create(admin,9,['1','贴合','OUTPUT-A','','',''])
    attendance=create(admin,4,['2026-10-01','OUTPUT-A','8','2','1','','','','',''])
    values=['2026-10-01','客户','产品','','OUTPUT-A','4','Y','','','','','','','2026-10-01 09:00:00','','','贴合','','25','']
    prod=create(admin,2,values)
    create(admin,2,['2026-10-02',*values[1:]])
    monkeypatch.setattr(workflow,'now_local',lambda:dt.datetime(2026,10,3,9,59,tzinfo=workflow.UTC7))
    first=admin.get('/api/reports/hourly-output?month=2026-10');assert first.status_code==200,first.text
    assert first.json()['cutoff']=='2026-10-01' and first.json()['hours']['2026-10-01']=='11'
    assert first.json()['amounts']=={'2026-10-01':'100'}
    changed_hours=attendance['values'].copy();changed_hours[2]='10'
    result=admin.post('/api/sync',json={'changes':[{'id':attendance['id'],'table':4,'version':1,'values':changed_hours}]})
    assert result.status_code==200,result.text
    assert admin.get('/api/reports/hourly-output?month=2026-10').json()['hours']=={'2026-10-01':'13'}
    assert admin.get('/api/reports/hourly-output?month=2026-10&action=export').json()['hours']=={'2026-10-01':'13'}
    changed=prod['values'].copy();changed[18]='50'
    admin.post('/api/sync',json={'changes':[{'id':prod['id'],'table':2,'version':1,'values':changed}]})
    assert admin.get('/api/reports/hourly-output?month=2026-10').json()['amounts']['2026-10-01']=='100'
    monkeypatch.setattr(workflow,'now_local',lambda:dt.datetime(2026,10,3,10,0,tzinfo=workflow.UTC7))
    second=admin.get('/api/reports/hourly-output?month=2026-10').json()
    assert second['cutoff']=='2026-10-02' and second['amounts']=={'2026-10-01':'200','2026-10-02':'100'}
    assert admin.post('/api/reports/hourly-output/target',json={'month':'2026-10','target':'42.5'}).status_code==200
    assert admin.get('/api/reports/hourly-output?month=2026-10').json()['target']=='42.5'


def test_only_excel_inventory_tables_are_available(setup):
    app,admin,store=setup
    new_stock=create(admin,12,['1','','NEW-CODE','新产品','新规格','58','白','Y','新仓','B1','0','10','0','10',''])
    new_ledger=create(admin,13,['2026-10-02','NEW-DOC','入库','贴合','','NEW-CODE','新产品','新规格','58','白','Y','新仓','B1','0','10','0','10','','2026-10-02 10:00:00'])
    assert len(new_stock['values'])==14 and len(new_ledger['values'])==18
    assert new_stock['values'][9:]==['0','0','0','0','']
    assert new_ledger['values'][12:]==['0','10','0','10','','2026-10-02 10:00:00']
    assert '库位' not in admin.get('/api/admin/roles').json()['catalog']['12']['fields']
    assert '库位' not in admin.get('/api/admin/roles').json()['catalog']['13']['fields']
    catalog=admin.get('/api/admin/roles').json()['catalog']
    assert '5' not in catalog and '6' not in catalog
    assert catalog['12']['name']=='即时库存' and catalog['13']['name']=='出入库明细表'
    for old in [5,6]:
        assert admin.get('/api/tables/'+str(old)).status_code==400
        assert admin.post('/api/sync',json={'changes':[{'id':str(uuid.uuid4()),'table':old,'version':0,'values':[]}]}).status_code==400
    assert admin.post('/api/inventory/generate-work',json={'ids':[]}).status_code==410
    # Existing roles move to the matching current table, preserving explicit newer grants.
    from psycopg.types.json import Jsonb
    with store.connect(write=True) as con:
        role=con.execute("SELECT id FROM jy_roles WHERE name='仓库人员'").fetchone()
        con.execute('UPDATE jy_roles SET permissions=%s WHERE id=%s',(Jsonb({'5':{'actions':['view','import'],'scope':'own'},'6':{'actions':['view'],'scope':'all'},'12':{'actions':['view'],'scope':'teams'}}),role['id']))
    store.initialize()
    role=next(r for r in admin.get('/api/admin/roles').json()['roles'] if r['name']=='仓库人员')
    assert '5' not in role['permissions'] and '6' not in role['permissions']
    assert role['permissions']['12']['scope']=='teams' and role['permissions']['13']=={'actions':['view'],'scope':'all'}


def test_attendance_two_leaders_preserve_independent_rows_and_scope(setup):
    from concurrent.futures import ThreadPoolExecutor
    app,admin,_=setup
    team=create(admin,9,['1','贴合','SHARED-A','','',''])
    role=admin.post('/api/admin/roles',json={'name':'独立考勤录入','permissions':{'4':{'scope':'own','actions':['view','create','update']}}}).json()
    role_id=role.get('id') or role.get('role',{}).get('id')
    for name in ['leader-a','leader-b']:user(admin,name,[role_id],[team['id']])
    with TestClient(app) as first,TestClient(app) as second:
        login(first,'leader-a',change=True);login(second,'leader-b',change=True)
        values=['2026-10-31','SHARED-A','8','2','1','','','','','']
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(create,first,4,values);b=pool.submit(create,second,4,values);a,b=a.result(),b.result()
        assert a['id']!=b['id'] and a['values'][10]!=b['values'][10]
        assert a['values'][12]=='leader-a' and b['values'][12]=='leader-b'
        assert first.get('/api/tables/4').json()['records'][0]['id']==a['id']
        assert len(admin.get('/api/tables/4').json()['records'])==2
        assert second.post('/api/sync',json={'changes':[{'id':a['id'],'table':4,'version':1,'values':a['values']}]}).status_code==403


def test_price_audit_permissions_and_duplicate_batch_are_atomic(setup):
    app,admin,_=setup
    first=create(admin,10,['','客户','MAT','58','产品','VND','1',''])
    duplicate=create(admin,10,['','客户','MAT','58','产品','VND','2',''])
    editor=admin.post('/api/admin/roles',json={'name':'价格维护','permissions':{'10':{'scope':'all','actions':['view','update']}}}).json()
    auditor=admin.post('/api/admin/roles',json={'name':'价格审核','permissions':{'10':{'scope':'all','actions':['view','approve_price','unapprove_price']}}}).json()
    eid=editor.get('id') or editor['role']['id'];aid=auditor.get('id') or auditor['role']['id']
    user(admin,'price-editor',[eid]);user(admin,'price-auditor',[aid])
    def payload(rows):return {'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':r['id'],'version':r['version']} for r in rows]}
    with TestClient(app) as edit,TestClient(app) as review:
        login(edit,'price-editor',change=True);login(review,'price-auditor',change=True)
        assert edit.post('/api/price-list/review',json=payload([first])).status_code==403
        assert review.post('/api/sync',json={'changes':[{'id':first['id'],'table':10,'version':1,'values':first['values']}]}).status_code==403
        assert review.post('/api/price-list/review',json=payload([first,duplicate])).status_code==409
        assert all(r['meta']['priceStatus']=='未审核' for r in admin.get('/api/tables/10').json()['records'])
        assert review.post('/api/price-list/review',json=payload([first])).status_code==200
        role=next(r for r in admin.get('/api/admin/roles').json()['roles'] if str(r['id'])==str(aid))
        assert admin.post('/api/admin/roles',json={**role,'permissions':{'10':{'scope':'all','actions':['view']}}}).status_code==200
        assert review.post('/api/price-list/review',json=payload([duplicate])).status_code==403


def test_frozen_hourly_snapshot_has_shared_target_and_scoped_totals(setup,monkeypatch):
    import datetime as dt
    import enterprise.business_workflows as workflow
    app,admin,_=setup
    team_a=create(admin,9,['1','贴合','SCOPE-A','','','']);team_b=create(admin,9,['2','泡棉','SCOPE-B','','',''])
    a=create(admin,4,['2026-10-01','SCOPE-A','8','0','0','','','','',''])
    create(admin,4,['2026-10-01','SCOPE-B','20','0','0','','','','',''])
    read=admin.post('/api/admin/roles',json={'name':'组别统计','permissions':{'11':{'scope':'teams','actions':['view']}}}).json()
    rid=read.get('id') or read['role']['id'];user(admin,'report-reader',[rid],[team_a['id']])
    monkeypatch.setattr(workflow,'now_local',lambda:dt.datetime(2026,10,3,10,0,tzinfo=workflow.UTC7))
    assert admin.get('/api/reports/hourly-output?month=2026-10').json()['hours']['2026-10-01']=='28'
    changed=a['values'].copy();changed[2]='80'
    assert admin.post('/api/sync',json={'changes':[{'id':a['id'],'table':4,'version':1,'values':changed}]}).status_code==200
    with TestClient(app) as reader:
        login(reader,'report-reader',change=True)
        assert reader.get('/api/tables/4').status_code==403
        assert reader.get('/api/reports/hourly-output?month=2026-10&action=export').status_code==403
        scoped=reader.get('/api/reports/hourly-output?month=2026-10').json()
        assert scoped['hours']=={'2026-10-01':'80'}
        assert 'groups' not in scoped
        assert reader.post('/api/reports/hourly-output/target',json={'month':'2026-10','target':'999'}).status_code==403
        assert admin.post('/api/reports/hourly-output/target',json={'month':'2026-10','target':'42'}).status_code==200
        assert reader.get('/api/reports/hourly-output?month=2026-10').json()['target']=='42'


def test_legacy_migration_skips_empty_attendance_and_resolves_team(setup):
    _,admin,_=setup
    tables=[[] for _ in range(10)]
    tables[9]=[['1','贴合','MIG-A','','','']]
    tables[4]=[['']*10,['2026-10-31','MIG-A','8','2','1','','','','','']]
    data={'tables':tables,'information':{},'scanMeta':[]}
    preview=admin.post('/api/admin/migration/preview',json=data)
    assert preview.status_code==200,preview.text
    assert preview.json()['counts']['4']==1
    response=admin.post('/api/admin/migration/commit',json={'data':data,'digest':preview.json()['digest']})
    assert response.status_code==200,response.text
    row=admin.get('/api/tables/4').json()['records'][0]
    assert row['teamId'] and row['values'][11]=='贴合' and row['values'][6]=='13'


def test_inventory_location_removal_preserves_balances_and_is_idempotent(setup):
    from psycopg.types.json import Jsonb
    _,admin,store=setup
    stock=['1','','CODE','品名','规格','58','白','Y','仓库','库位A','11','22','33','44','库存备注']
    ledger=['2026-11-01','DOC','入库','贴合','SO','CODE','品名','规格','58','白','Y','仓库','库位B','55','66','77','88','明细备注','2026-11-01 09:00:00']
    a=create(admin,12,stock);b=create(admin,13,ledger)
    with store.connect(write=True) as con:
        for row,values in [(a,stock),(b,ledger)]:con.execute('UPDATE jy_records SET values_json=%s WHERE id=%s',(Jsonb(values),row['id']))
    store.initialize()
    version=admin.get('/api/tables/12').json()['records'][0]['version']
    store.initialize()
    actual=admin.get('/api/tables/12').json()['records'][0]
    detail=admin.get('/api/tables/13').json()['records'][0]
    assert actual['values']==stock[:9]+['11','66','77','0','库存备注'] and actual['version']==version
    assert detail['values']==ledger[:12]+ledger[13:] and detail['version']==b['version']+1
    # Native new schemas are accepted; legacy uploads are also normalized above.
    values=actual['values'].copy();values[9]='99'
    updated=admin.post('/api/sync',json={'changes':[{'id':actual['id'],'table':12,'version':actual['version'],'values':values}]})
    assert updated.status_code==200 and updated.json()['records'][0]['values'][9]=='99'


def test_attendance_rate_is_three_and_server_ignores_forged_cost(setup):
    _,admin,_=setup
    create(admin,9,['1','贴合','RATE-3','','',''])
    row=create(admin,4,['2026-11-02','RATE-3','8','2','1','999','999','999','999',''])
    assert row['values'][5:9]==['11','13','3','39']
    values=row['values'].copy();values[2:5]=['0.1','0.2','0.3'];values[7]='1'
    response=admin.post('/api/sync',json={'changes':[{'id':row['id'],'table':4,'version':row['version'],'values':values}]})
    assert response.status_code==200,response.text
    assert response.json()['records'][0]['values'][5:9]==['0.6','1','3','3']


def test_price_serial_is_concurrent_unique_and_sales_production_fields_join(setup):
    from concurrent.futures import ThreadPoolExecutor
    app,admin,store=setup
    with TestClient(app) as second:
        login(second,'admin','Changed-test-password')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(create,admin,10,['','客户A','MAT','58','产品','VND','0.3',''])
            b=pool.submit(create,second,10,['','客户B','MAT','58','产品','VND','2',''])
            a,b=a.result(),b.result()
    assert {a['values'][0],b['values'][0]}=={'1','2'} and a['id']!=b['id']
    changed=a['values'].copy();changed[0]='999'
    assert admin.post('/api/sync',json={'changes':[{'id':a['id'],'table':10,'version':a['version'],'values':changed}]}).status_code==403
    create(admin,9,['1','贴合','JOIN-A','','',''])
    v=sale_values('JOIN-SALE');v[4]='客户A';v[7]='MAT';v[8]='CUSTOM-INSTRUCTION';v[9]='58';v[10]='产品'
    sale=create(admin,0,v)
    assert sale['values'][27:]==['','']
    response=admin.post('/api/price-list/review',json={'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':a['id'],'version':a['version']}]})
    assert response.status_code==200,response.text
    sale=admin.get('/api/tables/0').json()['records'][0];assert sale['values'][27:]==['VND','0.3']
    work=create(admin,1,['2026-11-02','JOIN-A','客户A','SO','OLD-INSTRUCTION','产品','MAT','OLD-SPEC','100','0','Y','','JOIN-SALE','贴合','MO-JOIN'])
    scan=create(admin,8,['2026-11-02 09:00:00','2026-11-01','贴合','JOIN-A','客户A','OLD-INSTRUCTION','产品','OLD-SPEC','3','','MO-JOIN','JOIN-SALE'])
    assert admin.post('/api/scan/submit',json={'ids':[scan['id']]}).status_code==200
    production=admin.get('/api/tables/2').json()['records'][0]
    assert production['values'][3]=='CUSTOM-INSTRUCTION' and production['values'][18:]==['0.3','0.9','58','VND']


def test_account_table_enforces_actual_node_permissions_and_never_returns_password(setup):
    app,admin,store=setup
    team=create(admin,9,['1','贴合','ACCESS-A','','',''])
    secret='Strong-test-130'
    def access(node,permission='允许',password=''):
        rid=str(uuid.uuid4());payload={'requestId':str(uuid.uuid4()),'changes':[{'id':rid,'version':0,'values':['','贴合','ACCESS-A','node-user',password,'班组长','即时库存',node,permission,'']}]} 
        response=admin.post('/api/access/rows',json=payload);assert response.status_code==200,response.text
        assert secret not in response.text
        return response.json()['records'][0]
    grant=access('全部操作',password=secret);deny=access('修改','不允许')
    assert grant['values'][4]=='****'
    with store.connect() as con:
        account=con.execute("SELECT * FROM jy_users WHERE username='node-user'").fetchone()
        assert account['password_hash'].startswith('$argon2') and secret not in str(con.execute('SELECT after_json FROM jy_audit WHERE table_id=14').fetchall())
    stock=create(admin,12,['1','','CODE','物料','规格','58','白','Y','仓库','10','','','',''])
    with TestClient(app) as member:
        login(member,'node-user',secret,change=True)
        assert member.get('/api/tables/12').status_code==200
        assert member.get('/api/tables/0').status_code==403
        assert member.get('/api/tables/14').status_code==403
        assert member.post('/api/sync',json={'changes':[{'id':stock['id'],'table':12,'version':stock['version'],'values':stock['values']}]}).status_code==403
        assert member.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[]}).status_code==403
        assert admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':grant['id'],'version':grant['version'],'delete':True},{'id':deny['id'],'version':deny['version'],'delete':True}]}).status_code==200
        assert member.get('/api/auth/me').status_code==401


def test_inventory_vouchers_update_stock_atomically_and_retry_once(setup):
    _,admin,_=setup
    stock=create(admin,12,['1','','CODE','物料','规格','58','白','Y','仓库','100','','','',''])
    expected_in=0;expected_out=0
    for kind in ['采购入库','产品入库','其它入库','盘盈入库','采购退货','生产领料','销售出库','其它出库','盘亏出库','生产退料']:
        current=next(r for r in admin.get('/api/tables/12').json()['records'] if r['id']==stock['id']);values=current['values'].copy();values[1]='3'
        response=admin.post('/api/sync',json={'changes':[{'id':stock['id'],'table':12,'version':current['version'],'values':values}]});assert response.status_code==200,response.text
        source=next(r for r in response.json()['records'] if r['id']==stock['id'])
        payload={'requestId':str(uuid.uuid4()),'date':'2026-11-02','type':kind,'partner':'贴合','warehouse':'仓库','note':'有效单据','records':[{'id':stock['id'],'version':source['version'],'information':'3'}]}
        result=admin.post('/api/inventory/post-voucher',json=payload);assert result.status_code==200,result.text
        assert admin.post('/api/inventory/post-voucher',json=payload).json()==result.json()
        inbound=kind in ['采购入库','产品入库','其它入库','盘盈入库','采购退货'];quantity=-3 if kind in ['采购退货','生产退料'] else 3
        ledger=next(r for r in result.json()['records'] if r['id']==result.json()['ids'][0]);assert ledger['values'][14 if inbound else 13]==''
        assert ledger['values'][12]==('100' if kind=='采购入库' else '')
        if inbound:expected_in+=quantity
        else:expected_out+=quantity
        current=admin.get('/api/tables/12').json()['records'][0]
        assert current['values'][1]=='' and current['values'][10:13]==[str(expected_in),str(expected_out),str(100+expected_in-expected_out)]
    assert len(admin.get('/api/tables/13').json()['records'])==10
    # Duplicate inventory keys (code intentionally differs) may not double-post.
    duplicate=create(admin,12,['2','2','OTHER-CODE','物料','规格','58','白','Y','仓库','0','','','',''])
    rejected={'requestId':str(uuid.uuid4()),'date':'2026-11-02','type':'采购入库','partner':'贴合','warehouse':'仓库','records':[{'id':duplicate['id'],'version':duplicate['version'],'information':'2'}]}
    assert admin.post('/api/inventory/post-voucher',json=rejected).status_code==409
    assert len(admin.get('/api/tables/13').json()['records'])==10


def test_inventory_batch_rejects_invalid_or_stale_rows_without_partial_writes(setup):
    from concurrent.futures import ThreadPoolExecutor
    app,admin,_=setup
    first=create(admin,12,['1','2','A','物料A','规格','58','白','Y','仓库','10','','','',''])
    second=create(admin,12,['2','bad','B','物料B','规格','58','白','Y','仓库','20','','','',''])
    base={'date':'2026-11-02','type':'采购入库','partner':'贴合','warehouse':'仓库'}
    batch={**base,'requestId':str(uuid.uuid4()),'records':[{'id':first['id'],'version':first['version'],'information':'2'},{'id':second['id'],'version':second['version'],'information':'bad'}]}
    assert admin.post('/api/inventory/post-voucher',json=batch).status_code==400
    assert admin.get('/api/tables/13').json()['records']==[]
    assert next(r for r in admin.get('/api/tables/12').json()['records'] if r['id']==first['id'])['values'][1]=='2'
    request={**base,'requestId':str(uuid.uuid4()),'records':[batch['records'][0]]}
    assert admin.post('/api/inventory/post-voucher',json={**request,'warehouse':'其它仓库'}).status_code==400
    with TestClient(app) as other:
        login(other,'admin','Changed-test-password')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(admin.post,'/api/inventory/post-voucher',json=request)
            b=pool.submit(other.post,'/api/inventory/post-voucher',json={**request,'requestId':str(uuid.uuid4())})
            responses=[a.result(),b.result()]
    assert sorted(r.status_code for r in responses)==[200,409]
    rows=admin.get('/api/tables/13').json()['records'];assert len(rows)==1
    assert rows[0]['values'][12:15]==['10','2','']
    stock=next(r for r in admin.get('/api/tables/12').json()['records'] if r['id']==first['id']);assert stock['values'][1]=='' and stock['values'][12]=='12'


def test_explicit_node_deny_overrides_existing_role_immediately(setup):
    app,admin,_=setup
    role=roles(admin)['管理只读'];user(admin,'old-role-user',[str(role['id'])])
    with TestClient(app) as reader:
        login(reader,'old-role-user',change=True)
        assert reader.get('/api/tables/0').status_code==200
        payload={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['','','','old-role-user','','文员','销售订单列表','查看','不允许','']}]} 
        result=admin.post('/api/access/rows',json=payload);assert result.status_code==200,result.text
        assert reader.get('/api/tables/0').status_code==403
        assert reader.get('/api/tables/14').status_code==403


def test_legacy_price_uuid_upgrades_to_immutable_numeric_key_without_changing_record_id(setup):
    from psycopg.types.json import Jsonb
    _,admin,store=setup
    row=create(admin,10,['','客户','MAT','58','产品','VND','1',''])
    approved=admin.post('/api/price-list/review',json={'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':row['id'],'version':row['version']}]}).json()['records'][0]
    values=approved['values'].copy();values[0]=row['id']
    with store.connect(write=True) as con:con.execute('UPDATE jy_records SET values_json=%s WHERE id=%s',(Jsonb(values),row['id']))
    store.initialize();first=admin.get('/api/tables/10').json()['records'][0]
    store.initialize();second=admin.get('/api/tables/10').json()['records'][0]
    assert first['id']==second['id']==row['id'] and first['values'][0].isdigit() and first['values'][0]==second['values'][0]
    assert first['meta']['priceStatus']=='已审核' and first['version']==second['version']


def test_price_migration_preserves_numeric_numbers_and_advances_sequence(setup):
    _,admin,_=setup
    tables=[[] for _ in range(15)]
    tables[10]=[['5','客户A','MAT','58','产品','VND','1',''],['9','客户B','MAT','58','产品','VND','2','']]
    data={'tables':tables,'information':{},'scanMeta':[]}
    preview=admin.post('/api/admin/migration/preview',json=data)
    assert preview.status_code==200,preview.text
    response=admin.post('/api/admin/migration/commit',json={'data':data,'digest':preview.json()['digest']})
    assert response.status_code==200,response.text
    assert {r['values'][0] for r in admin.get('/api/tables/10').json()['records']}=={'5','9'}
    assert create(admin,10,['','客户C','MAT','58','产品','VND','3',''])['values'][0]=='10'


def test_access_password_retry_never_accepts_changed_secret_or_clears_profile(setup):
    _,admin,store=setup
    team=create(admin,9,['1','贴合','PROFILE-A','','',''])
    values=['','贴合','PROFILE-A','retry-user','Strong-retry-130','文员','即时库存','查看','允许','']
    payload={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':values}]}
    response=admin.post('/api/access/rows',json=payload)
    assert response.status_code==200,response.text
    assert admin.post('/api/access/rows',json=payload).json()==response.json()
    changed=json.loads(json.dumps(payload));changed['changes'][0]['values'][4]='Different-retry-130'
    assert admin.post('/api/access/rows',json=changed).status_code==409
    extra=['','','','retry-user','','文员','即时库存','修改','不允许','']
    assert admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':extra}]}).status_code==200
    with store.connect() as con:
        account=con.execute("SELECT * FROM jy_users WHERE username='retry-user'").fetchone()
        assert account['department']=='贴合' and account['team_ids']==[team['id']]


def test_inventory_voucher_appends_after_existing_ledger_and_preserves_batch_order(setup):
    _,admin,_=setup
    prior=create(admin,13,['2026-11-01','OLD','采购入库','贴合','','OLD','旧物料','','','','Y','仓库','0','1','0','','',''])
    sources=[create(admin,12,[str(i),'2','CODE-'+str(i),'物料'+str(i),'规格','58','白','Y','仓库','10','','','','']) for i in [1,2]]
    response=admin.post('/api/inventory/post-voucher',json={'requestId':str(uuid.uuid4()),'date':'2026-11-02','type':'采购入库','partner':'贴合','warehouse':'仓库','records':[{'id':r['id'],'version':r['version'],'information':'2'} for r in sources]})
    assert response.status_code==200,response.text
    rows=admin.get('/api/tables/13').json()['records']
    assert [r['id'] for r in rows]==[prior['id'],*response.json()['ids']]
    assert [r['values'][6] for r in rows]==['旧物料','物料1','物料2']
    assert [r['id'] for r in admin.get('/api/tables/13').json()['records']]==[r['id'] for r in rows]


def test_access_accepts_short_empty_long_passwords_and_disallow_permissions(setup):
    app,admin,store=setup
    for name,password in [('short-access','123'),('empty-access',''),('long-access','x'*256)]:
        rid=str(uuid.uuid4());values=['','','',name,password,'文员','即时库存','查看','允许','']
        payload={'requestId':str(uuid.uuid4()),'changes':[{'id':rid,'version':0,'values':values}]}
        response=admin.post('/api/access/rows',json=payload);assert response.status_code==200,response.text
        grant=response.json()['records'][0];assert grant['values'][4]=='****'
        assert admin.post('/api/access/rows',json=payload).json()==response.json()
        with TestClient(app) as member:
            login(member,name,password)
            assert member.get('/api/auth/me').json()['user']['must_change_password'] is False
            assert member.get('/api/tables/12').status_code==200
        # Blank on an existing record preserves its current password.
        modified=grant['values'].copy();modified[4]='';modified[9]='保留密码'
        saved=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':rid,'version':grant['version'],'values':modified}]})
        assert saved.status_code==200,saved.text
        with TestClient(app) as member:login(member,name,password)
    deny=['','','','short-access','','文员','即时库存','修改','不允许','']
    response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':deny}]})
    assert response.status_code==200,response.text
    with TestClient(app) as member:
        login(member,'short-access','123')
        assert member.get('/api/auth/me').json()['user']['permissions']['12']['update']==[]
    deny[8]='禁止'
    assert admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':deny}]}).status_code==400


def test_access_legacy_denial_migrates_once_and_still_denies(setup):
    from psycopg.types.json import Jsonb
    app,admin,store=setup
    response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['','','','legacy-denial','','文员','即时库存','查看','不允许','']}]})
    assert response.status_code==200,response.text
    record=response.json()['records'][0];legacy=record['values'].copy();legacy[8]='禁止'
    with store.connect(write=True) as con:con.execute('UPDATE jy_records SET values_json=%s WHERE id=%s',(Jsonb(legacy),record['id']))
    store.initialize();store.initialize()
    row=next(r for r in admin.get('/api/tables/14').json()['records'] if r['id']==record['id'])
    assert row['values'][8]=='不允许' and row['version']==record['version']+1
    with TestClient(app) as member:
        login(member,'legacy-denial','')
        assert member.get('/api/tables/12').status_code==403


def test_access_free_department_team_and_table_tab_visibility(setup):
    app,admin,store=setup
    create(admin,9,['1','主数据部门','已有班组','','',''])
    username='tab-visibility'
    def add(table,node,permission,department='自由填写部门',team='已有班组'):
        response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['',department,team,username,'','文员',table,node,permission,'']}]})
        assert response.status_code==200,response.text
        return response.json()['records'][0]
    stock=add('即时库存','表标签可看','允许')
    sale=add('销售订单列表','表标签可看','不允许',team='完全未登记班组')
    add('销售订单列表','全部操作','允许')
    assert stock['values'][1:3]==['自由填写部门','已有班组']
    assert sale['values'][1:3]==['自由填写部门','完全未登记班组']
    with store.connect() as con:
        account=con.execute('SELECT * FROM jy_users WHERE username=%s',(username,)).fetchone()
        assert account['department']=='自由填写部门' and account['team_ids']==[]
    with TestClient(app) as member:
        login(member,username,'')
        permissions=member.get('/api/auth/me').json()['user']['permissions']
        assert permissions['12']['view']==['all'] and permissions['0']['view']==[]
        assert member.get('/api/tables/12').status_code==200 and member.get('/api/tables/0').status_code==403
        # An administrator can restore the visible table without editing its other grants.
        values=sale['values'].copy();values[8]='允许'
        updated=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':sale['id'],'version':sale['version'],'values':values}]})
        assert updated.status_code==200,updated.text
        assert member.get('/api/tables/0').status_code==200


def test_permission_node_names_match_toolbar_and_frontend_backend_catalogs():
    import ast,re
    from enterprise.access_workflows import NODES
    root=Path(__file__).resolve().parents[2]
    source=(root/'access-table.js').read_text()
    match=re.search(r'const primaryNodes=(\{.*?\});const legacyNodes=(\{.*?\});',source)
    assert match
    primary,legacy=map(json.loads,match.groups())
    assert {**primary,**legacy}==NODES
    actions=ast.literal_eval(re.search(r'const actions=(\[.*?\]);',(root/'app.js').read_text()).group(1))
    toolbar={('导入EXCEL' if '上传' in name else name.replace('EXCEL表','EXCEL')) for group in actions for name in group}
    assert toolbar<=primary.keys()
    assert {'保存','确定','订单关闭','下推生成生产工单','下推生成生产报表','启用摄像头','清空扫码记录','目标设置'}<=primary.keys()


def test_actual_button_node_names_and_legacy_aliases_enforce_same_actions(setup):
    app,admin,_=setup
    def put(node,permission):
        response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['','','','button-nodes','','文员','销售订单列表',node,permission,'']}]})
        assert response.status_code==200,response.text
        return response.json()['records'][0]
    put('下推生成生产工单','允许');put('订单关闭','允许')
    old=put('下推生产工单','不允许')
    with TestClient(app) as member:
        login(member,'button-nodes','')
        permissions=member.get('/api/auth/me').json()['user']['permissions']['0']
        assert permissions['generate_work']==[] and permissions['close_order']==['all']
        response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':old['id'],'version':old['version'],'delete':True}]})
        assert response.status_code==200,response.text
        assert member.get('/api/auth/me').json()['user']['permissions']['0']['generate_work']==['all']
    # All literal names from the user's toolbar/import format are accepted.
    for node in ['保存','确定','下推生成生产报表','关闭','新增班组','审核','反审','下退生成出入库单据','下推生成出入库单据','启用摄像头','启用设像头','清空扫码记录','目标设置']:
        put(node,'不允许')


def test_financial_fields_are_hidden_in_api_export_retry_and_preserved_on_edits(setup):
    app,admin,_=setup
    create(admin,9,['1','贴合','FIN-A','','',''])
    price_row=create(admin,10,['','金融客户','MAT','SPEC','金融产品','VND','17.25',''])
    reviewed=admin.post('/api/price-list/review',json={'requestId':str(uuid.uuid4()),'approve':True,'records':[{'id':price_row['id'],'version':price_row['version']}]})
    assert reviewed.status_code==200,reviewed.text
    values=sale_values('FIN-ID');values[4]='金融客户';values[7]='MAT';values[9]='SPEC';values[10]='金融产品'
    sale=create(admin,0,values)
    assert sale['values'][28]=='17.25'
    production=create(admin,2,['2026-11-02','无匹配金融客户','金融产品','','FIN-A','4','Y','','','','','','','2026-11-02 10:00:00','','','贴合','','7.25','','SPEC','VND'])
    assert production['values'][18:20]==['7.25','29']
    grants=[]
    for table in ['销售订单列表','各工序每日生产明细表','单价表']:
        for node,permission in [('全部操作','允许'),('单价和金额查看','不允许')]:
            response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['','','','finance-user','','文员',table,node,permission,'']}]})
            assert response.status_code==200,response.text
            if node=='单价和金额查看':grants+=response.json()['records']
    with TestClient(app) as member:
        login(member,'finance-user','')
        for table,indices in [(0,[28]),(2,[18,19]),(10,[6])]:
            rows=member.get('/api/tables/'+str(table));assert rows.status_code==200,rows.text
            assert all(row['values'][i]=='' for row in rows.json()['records'] for i in indices)
            exported=member.post('/api/tables/'+str(table)+'/authorize',json={'action':'export'})
            assert exported.status_code==200,exported.text
            assert all(row['values'][i]=='' for row in exported.json()['records'] for i in indices)
        hidden=member.get('/api/tables/2').json()['records'][0];edited=hidden['values'].copy();edited[5]='6';edited[11]='可以修改非金额字段'
        payload={'requestId':str(uuid.uuid4()),'changes':[{'id':hidden['id'],'table':2,'version':hidden['version'],'values':edited}]}
        saved=member.post('/api/sync',json=payload);assert saved.status_code==200,saved.text
        result=next(r for r in saved.json()['records'] if r['id']==hidden['id']);assert result['values'][18:20]==['','']
        assert member.post('/api/sync',json=payload).json()==saved.json()
        authoritative=admin.get('/api/tables/2').json()['records'][0]
        assert authoritative['values'][18:20]==['7.25','43.5']
        tampered=result['values'].copy();tampered[18]='999'
        assert member.post('/api/sync',json={'changes':[{'id':result['id'],'table':2,'version':result['version'],'values':tampered}]}).status_code==403
        # Granting visibility restores the original values; no financial data was cleared.
        response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':g['id'],'version':g['version'],'values':[*(g['values'][:8]),'允许',g['values'][9]]} for g in grants]})
        assert response.status_code==200,response.text
        assert member.get('/api/tables/0').json()['records'][0]['values'][28]=='17.25'
        assert member.get('/api/tables/2').json()['records'][0]['values'][18:20]==['7.25','43.5']


def test_financial_visibility_defaults_to_existing_view_permission(setup):
    app,admin,_=setup
    row=create(admin,10,['','原有查看用户','MAT','SPEC','产品','VND','3.5',''])
    role=roles(admin)['管理只读'];user(admin,'legacy-financial-reader',[str(role['id'])])
    with TestClient(app) as reader:
        login(reader,'legacy-financial-reader',change=True)
        data=reader.get('/api/tables/10');assert data.status_code==200,data.text
        assert data.json()['records'][0]['values'][6]=='3.5'
        assert reader.get('/api/auth/me').json()['user']['permissions']['10']['financial_view']==['all']


def test_password_visibility_requires_explicit_permission_and_never_exports_secret(setup):
    app,admin,store=setup
    secret='Vault-test-146'
    def access(name,node,permission,password=''):
        response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['','','',name,password,'文员','用户与权限',node,permission,'']}]})
        assert response.status_code==200,response.text
        return response.json()['records'][0]
    target=access('vault-person','表标签可看','允许',secret)
    assert admin.get('/api/access/passwords').status_code==403
    access('admin','全部操作','允许')
    assert admin.get('/api/access/passwords').status_code==403
    permit=access('admin','密码是否见','允许')
    result=admin.get('/api/access/passwords');assert result.status_code==200,result.text
    assert result.json()['passwords']['vault-person']=={'available':True,'value':secret}
    assert 'no-store' in result.headers['cache-control']
    for response in [admin.get('/api/tables/14'),admin.post('/api/tables/14/authorize',json={'action':'export'})]:
        assert response.status_code==200 and secret not in response.text
        assert all(row['values'][4]=='****' for row in response.json()['records'])
    with store.connect() as con:
        account=con.execute("SELECT * FROM jy_users WHERE username='vault-person'").fetchone()
        assert account['password_cipher'] and secret not in account['password_cipher']
        assert secret not in str(con.execute('SELECT before_json,after_json FROM jy_audit').fetchall())
    access('vault-person','密码是否见','允许')
    with TestClient(app) as member:
        login(member,'vault-person',secret)
        assert member.get('/api/access/passwords').status_code==403
        assert member.get('/api/tables/14').status_code==403
    deny=permit['values'].copy();deny[4]='';deny[8]='不允许'
    assert admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':permit['id'],'version':permit['version'],'values':deny}]}).status_code==200
    assert admin.get('/api/access/passwords').status_code==403
    assert admin.get('/api/auth/me').json()['user']['permissions']['14']['password_view']==[]


def test_legacy_password_recovery_after_verified_login_and_empty_password_visibility(setup):
    app,admin,store=setup
    def insert(name,password,node='表标签可看'):
        response=admin.post('/api/access/rows',json={'requestId':str(uuid.uuid4()),'changes':[{'id':str(uuid.uuid4()),'version':0,'values':['','','',name,password,'文员','用户与权限',node,'允许','']}]})
        assert response.status_code==200,response.text
        return response.json()['records'][0]
    insert('admin','','密码是否见');insert('legacy-vault','Legacy-vault-146');insert('empty-vault','')
    with store.connect(write=True) as con:con.execute("UPDATE jy_users SET password_cipher=NULL WHERE username='legacy-vault'")
    before=admin.get('/api/access/passwords').json()['passwords']
    assert before['legacy-vault']=={'available':False,'value':''}
    assert before['empty-vault']=={'available':True,'value':''}
    with TestClient(app) as member:
        login(member,'legacy-vault','Legacy-vault-146')
        after=admin.get('/api/access/passwords').json()['passwords']
        assert after['legacy-vault']['value']=='Legacy-vault-146'
        changed=member.post('/api/auth/password',json={'oldPassword':'Legacy-vault-146','newPassword':'Changed-vault-146'})
        assert changed.status_code==200,changed.text
        assert admin.get('/api/access/passwords').json()['passwords']['legacy-vault']['value']=='Changed-vault-146'
    from enterprise.password_vault import read_password
    with store.connect() as con:
        cipher=con.execute("SELECT password_cipher FROM jy_users WHERE username='legacy-vault'").fetchone()['password_cipher']
        assert read_password('different-name',cipher) is None
