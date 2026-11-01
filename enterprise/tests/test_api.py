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
        con.execute('TRUNCATE jy_audit,jy_sessions,jy_records,jy_drafts,jy_migrations,jy_users,jy_roles,jy_login_attempts RESTART IDENTITY CASCADE')
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
    team=create(admin,9,['1','生产','PROD#','','',''])
    work=create(admin,1,['2026/11/1','PROD#','客户','SO','PO','产品','','58','100',0,'Y','备注','PROD-SALE','贴合','MO-261101-01'])
    response=admin.post('/api/work-orders/generate-reports',json={'ids':[work['id']]})
    assert response.status_code==200,response.text
    report=admin.get('/api/tables/2').json()['records'][0]
    assert len(report['values'])==18 and report['values'][17]=='MO-261101-01'
    assert report['values'][3]=='100' and report['values'][12]=='PROD-SALE'
    assert admin.post('/api/work-orders/generate-reports',json={'ids':[work['id']]}).json()['ids']==[]
    from psycopg.types.json import Jsonb
    legacy=report['values'][:17];legacy[7:11]=['3','5','保留原因','原责任人']
    with store.connect(write=True) as con:
        con.execute('UPDATE jy_records SET values_json=%s WHERE id=%s',(Jsonb(legacy),report['id']))
    store.initialize()
    upgraded=admin.get('/api/tables/2').json()['records'][0]
    assert upgraded['values'][:17]==legacy and upgraded['values'][17]=='MO-261101-01'
