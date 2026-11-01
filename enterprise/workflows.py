"""Privileged workflow transitions, never emulated by arbitrary record updates."""
import copy
import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation, localcontext

from fastapi import Request
from psycopg.types.json import Jsonb

from .work_state import work_state
from .db import BUSINESS_TABLES, CATALOG, UTC7, audit, canonical, in_scope, is_admin, public_record, scopes


def register_workflows(app, store):
    from .api import (administrator, body, current_user, fail, insert_record, normalize_information,
                      number, quantity_text, record_by_id, require, resolve_team, text, uid,
                      validate_values, visible_rows)

    def stamp():
        return dt.datetime.now(UTC7).strftime('%Y/%-m/%-d %-H:%M %S')

    def remaining_quantity(con, values):
        sid=source_id(values)
        rows=con.execute('SELECT values_json FROM jy_records WHERE table_id=1 AND btrim(values_json->>12)=%s',(sid,)).fetchall()
        try:
            with localcontext() as context:
                context.prec=100
                order=Decimal(str(values[14]).replace(',','').replace('，','').strip())
                issued=sum((Decimal(str(r['values_json'][8]).replace(',','').replace('，','').strip()) for r in rows),Decimal(0))
                if not order.is_finite() or not issued.is_finite() or order<0 or issued<0: raise InvalidOperation()
                return order-issued
        except (InvalidOperation,ValueError):
            fail(400,'订单或已下达工单数量无效')

    def source_id(values):
        value=str(values[21]).strip()
        if not value:fail(400,'订单子表ID为空，不能下推')
        return value

    def draft_scope(row):
        return {'owner_id': row['owner_id'], 'team_id': row['team_id'], 'department': ''}

    def reserve_document_number(con):
        day=dt.datetime.now(UTC7).strftime('%y%m%d');prefix='MO-'+day+'-'
        floor=con.execute("SELECT COALESCE(max(substring(number from '[0-9]+$')::bigint),0) AS value FROM (SELECT COALESCE(NULLIF(meta->>'documentNo',''),values_json->>14) AS number FROM jy_records WHERE table_id=1 UNION ALL SELECT payload->>'documentNo' FROM jy_drafts) docs WHERE number ~ %s",('^'+prefix+'[0-9]+$',)).fetchone()['value']
        value=con.execute('INSERT INTO jy_document_sequences(day,last_value) VALUES(%s,%s) ON CONFLICT(day) DO UPDATE SET last_value=GREATEST(jy_document_sequences.last_value,%s)+1 RETURNING last_value',(day,floor+1,floor)).fetchone()['last_value']
        return prefix+str(value).zfill(2)

    def ensure_draft_number(con,row):
        payload=copy.deepcopy(row['payload']);changed=False
        if not payload.get('documentNo'):
            payload['documentNo']=reserve_document_number(con);changed=True
        if '工单号' not in payload['fields']:
            payload['fields'].append('工单号');changed=True
        for entries in [payload['rows'],payload['_originalRows']]:
            for entry in entries:
                if len(entry['values'])==15: entry['values'].append(payload['documentNo']);changed=True
        if changed:
            payload['revision']=payload.get('revision',0)+1
            con.execute('UPDATE jy_drafts SET payload=%s,version=version+1,printed_version=NULL WHERE id=%s',(Jsonb(payload),row['id']))
            row=con.execute('SELECT * FROM jy_drafts WHERE id=%s',(row['id'],)).fetchone()
        return row

    def draft_public(row):
        payload = {k: v for k, v in row['payload'].items() if not k.startswith('_')}
        payload['printedRevision'] = payload.get('revision',0) if row['printed_version']==row['version'] else -1
        return payload | {'serverId': str(row['id']), 'serverVersion': row['version'],
                          'serverPrinted': row['printed_version'] == row['version']}

    def get_draft(con, user, draft_id, action):
        row = con.execute('SELECT * FROM jy_drafts WHERE id=%s', (uid(draft_id),)).fetchone()
        if not row or (str(row['owner_id']) != str(user['id']) and not is_admin(con, user)):
            fail(404, '工单草稿不存在')
        require(con, user, 1, action, draft_scope(row))
        return row

    @app.post('/api/tables/{table}/authorize')
    async def authorize(table: int, request: Request):
        data = await body(request)
        action = data.get('action')
        if action not in ['export', 'label_print', 'report_print']:
            fail(400, '动作无效')
        with store.connect(write=True) as con:
            user, _ = current_user(request, con)
            rows = visible_rows(con, user, table, action)
            rows = [r for r in rows if in_scope(user, r, scopes(con, user, table, 'view'))]
            audit(con, user, action+'.requested', table, after={'records': len(rows)})
            result={'records': [public_record(r) for r in rows]}
            if action=='label_print' and table in [0,1]:
                job_id=str(uuid.uuid4())
                snapshot=[{'id':str(r['id']),'version':r['version'],'information':r['information']} for r in rows if r['information'].strip()]
                con.execute('INSERT INTO jy_label_jobs(id,owner_id,table_id,snapshot) VALUES(%s,%s,%s,%s)',(job_id,user['id'],table,Jsonb(snapshot)))
                result['jobId']=job_id
            return result

    @app.get('/api/references/attendance-teams')
    def attendance_teams(request: Request):
        with store.connect() as con:
            user,_=current_user(request,con)
            require(con,user,4,'view')
            if not scopes(con,user,4,'update') and not scopes(con,user,4,'create'):
                fail(403,'没有维护生产组别的权限')
            rows=con.execute("SELECT values_json->>2 AS name FROM jy_records WHERE table_id=9 AND btrim(values_json->>2)<>'' ORDER BY values_json->>2").fetchall()
            return {'names':list(dict.fromkeys(row['name'].strip() for row in rows))}

    @app.post('/api/labels/jobs/{job_id}/consume')
    async def consume_labels(job_id: str, request: Request):
        await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con)
            job=con.execute('SELECT * FROM jy_label_jobs WHERE id=%s',(uid(job_id),)).fetchone()
            if not job or str(job['owner_id'])!=str(user['id']): fail(404,'标签打印批次不存在')
            require(con,user,job['table_id'],'label_print')
            if job['consumed_at']: return job['result']
            cleared=changed=0
            for entry in job['snapshot']:
                row=con.execute('SELECT * FROM jy_records WHERE id=%s',(entry['id'],)).fetchone()
                if not row: continue
                require(con,user,job['table_id'],'label_print',row)
                if row['version']!=entry['version'] or row['information']!=entry['information']:
                    changed+=1;continue
                con.execute("UPDATE jy_records SET information='',version=version+1,updated_at=now() WHERE id=%s",(row['id'],))
                audit(con,user,'label.print_confirmed_clear',job['table_id'],str(row['id']),before={'information':row['information']},after={'information':'','jobId':str(job['id'])})
                cleared+=1
            result={'cleared':cleared,'changed':changed}
            con.execute('UPDATE jy_label_jobs SET consumed_at=now(),result=%s WHERE id=%s',(Jsonb(result),job['id']))
            return result

    @app.post('/api/sales/close')
    async def close_orders(request: Request):
        data = await body(request)
        with store.connect(write=True) as con:
            user, _ = current_user(request, con)
            ids = data.get('ids', [])
            if not isinstance(ids, list) or not ids: fail(400, '请先勾选订单')
            output = []
            for record_id in set(ids):
                row = record_by_id(con, record_id, 0)
                require(con, user, 0, 'close_order', row)
                if str(row['values_json'][0]).strip() in ['关闭','已关闭']:
                    output.append(public_record(row));continue
                values = row['values_json'].copy(); values[0] = '关闭'
                metadata={**row['meta'],'closedFrom':str(row['values_json'][0]).strip()}
                con.execute('UPDATE jy_records SET values_json=%s,meta=%s,version=version+1,updated_at=now() WHERE id=%s', (Jsonb(values), Jsonb(metadata), row['id']))
                audit(con, user, 'sales.close', 0, str(row['id']), before=public_record(row), after={'values': values})
                output.append(public_record(record_by_id(con, row['id'])))
            return {'records': output}

    @app.post('/api/sales/reopen')
    async def reopen_orders(request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con);ids=data.get('ids',[])
            if not isinstance(ids,list) or not ids:fail(400,'请先勾选订单')
            output=[]
            for record_id in set(ids):
                row=record_by_id(con,record_id,0);require(con,user,0,'reopen_order',row)
                if str(row['values_json'][0]).strip() not in ['关闭','已关闭']:
                    output.append(public_record(row));continue
                values=row['values_json'].copy();metadata=row['meta'].copy()
                prior=metadata.pop('closedFrom',None)
                values[0]=prior if prior and prior not in ['关闭','已关闭'] else '审核'
                con.execute('UPDATE jy_records SET values_json=%s,meta=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(values),Jsonb(metadata),row['id']))
                audit(con,user,'sales.reopen',0,str(row['id']),before=public_record(row),after={'values':values})
                output.append(public_record(record_by_id(con,row['id'])))
            return {'records':output}

    @app.get('/api/work-drafts')
    def drafts(request: Request):
        with store.connect(write=True) as con:
            user, _ = current_user(request, con)
            require(con, user, 1, 'view')
            rows = con.execute('SELECT * FROM jy_drafts WHERE owner_id=%s AND completed_at IS NULL ORDER BY updated_at DESC', (user['id'],)).fetchall()
            return {'drafts': [draft_public(ensure_draft_number(con,row)) for row in rows if in_scope(user, draft_scope(row), scopes(con,user,1,'draft_edit'))]}

    @app.post('/api/work-drafts')
    async def create_draft(request: Request):
        data = await body(request)
        with store.connect(write=True) as con:
            user, _ = current_user(request, con)
            require(con, user, 0, 'generate_work'); require(con, user, 1, 'draft_edit')
            ids, kind, team_id = data.get('ids'), data.get('type'), uid(data.get('teamId'))
            if not isinstance(ids, list) or not ids or len(ids) > 10000 or len(set(ids)) != len(ids) or kind not in ['泡棉','贴合']:
                fail(400, '订单、生产类型或班组无效')
            team = record_by_id(con, team_id, 9)
            if not str(team['values_json'][2]).strip(): fail(400,'请先维护生产班组名称')
            existing = con.execute('SELECT * FROM jy_drafts WHERE owner_id=%s AND completed_at IS NULL LIMIT 1', (user['id'],)).fetchone()
            if existing:
                require(con,user,1,'draft_edit',draft_scope(existing))
                return {'draft': draft_public(ensure_draft_number(con,existing)), 'resumed': True}
            scope_record = {'owner_id': user['id'], 'team_id': team_id, 'department': user['department']}
            require(con, user, 1, 'draft_edit', scope_record)
            created_at, rows = stamp(), []
            for record_id in ids:
                sale = record_by_id(con, record_id, 0); require(con,user,0,'generate_work',sale)
                v = sale['values_json']; sid = source_id(v)
                if str(v[0]).strip() in ['关闭','已关闭','已完成']:
                    fail(409, '包含已关闭或完成的销售订单')
                remaining=remaining_quantity(con,v)
                if remaining<=0: fail(409,'订单累计已下达数量已达到订单数量：'+sid)
                values = ['',created_at,team['values_json'][2],v[4],v[5],v[8],v[10],v[7],v[9],quantity_text(format(remaining,'f')),0,v[13],v[17],sid,kind]
                rows.append({'key': str(uuid.uuid4()), 'sourceRecordId': str(sale['id']), 'sourceSalesId': sid, 'values': values})
            document_no=reserve_document_number(con)
            for entry in rows: entry['values'].append(document_no)
            fields = ['信息录入'] + CATALOG['1']['fields']
            payload = {'version':1,'layoutVersion':4,'fields':fields,'type':kind,'group':team['values_json'][2],
                       'createdAt':created_at,'documentNo':document_no,'preparer':user['name'],'revision':0,'printedRevision':-1,
                       'rows':rows,'columns':[], '_originalRows':copy.deepcopy(rows)}
            draft_id = str(uuid.uuid4())
            con.execute('INSERT INTO jy_drafts(id,owner_id,team_id,payload) VALUES(%s,%s,%s,%s)', (draft_id,user['id'],team_id,Jsonb(payload)))
            audit(con,user,'work.draft.create',1,draft_id,after={'sources':ids,'type':kind,'teamId':team_id})
            return {'draft': draft_public(con.execute('SELECT * FROM jy_drafts WHERE id=%s',(draft_id,)).fetchone())}

    @app.post('/api/work-drafts/{draft_id}/save')
    async def save_draft(draft_id: str, request: Request):
        data = await body(request)
        with store.connect(write=True) as con:
            user, _ = current_user(request, con); old = get_draft(con,user,draft_id,'draft_edit')
            if old['completed_at']: fail(409, '工单已确定')
            if data.get('version') != old['version']: fail(409, '草稿已被修改，请重新打开')
            proposed = data.get('draft', {})
            if not isinstance(proposed, dict) or not isinstance(proposed.get('rows'),list): fail(400, '草稿格式无效')
            if proposed.get('documentNo',old['payload'].get('documentNo'))!=old['payload'].get('documentNo'): fail(403,'工单号由后台生成，不能修改')
            originals = {r['key']: r for r in old['payload']['_originalRows']}
            seen, rows = set(), []
            for row in proposed['rows']:
                key = row.get('key'); original = originals.get(key)
                if not original or key in seen: fail(400, '草稿包含未选择的订单或重复行')
                seen.add(key)
                values = row.get('values')
                if not isinstance(values,list) or len(values)!=16: fail(400, '草稿字段无效')
                validated = validate_values(1, values[1:])
                values = [normalize_information(values[0])] + validated
                editable = {3,4,5,6,7,8,9,12}
                if any(str(values[i])!=str(original['values'][i]) for i in range(16) if i not in editable and i!=0):
                    fail(403, '工单ID、日期、设备和系统字段不可直接修改')
                rows.append({**original, 'values':values})
            payload = copy.deepcopy(old['payload'])
            payload['rows'] = rows
            payload['preparer'] = text(proposed.get('preparer',''),'制表',200,True)
            columns = proposed.get('columns', [])
            if not isinstance(columns,list) or len(columns)>15: fail(400, '列设置无效')
            for c in columns:
                if not isinstance(c,dict) or c.get('n') not in payload['fields']+['二维码'] or type(c.get('w')) not in (float,int) or not 20<=c['w']<=3000:
                    fail(400,'列宽无效')
            payload['columns'] = columns
            payload['layoutVersion'] = proposed.get('layoutVersion',payload.get('layoutVersion',3))
            # UI revision markers do not invalidate an otherwise identical server document.
            payload['revision'] = proposed.get('revision',payload.get('revision',0))
            changed = any(canonical(payload.get(k)) != canonical(old['payload'].get(k)) for k in ['rows','preparer','columns','layoutVersion'])
            if changed:
                con.execute('UPDATE jy_drafts SET payload=%s,version=version+1,printed_version=NULL,updated_at=now() WHERE id=%s',(Jsonb(payload),old['id']))
                audit(con,user,'work.draft.update',1,str(old['id']),before={'rows':old['payload']['rows']},after={'rows':rows})
            return {'draft':draft_public(con.execute('SELECT * FROM jy_drafts WHERE id=%s',(old['id'],)).fetchone())}

    @app.post('/api/work-drafts/{draft_id}/print')
    async def print_draft(draft_id: str, request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con); row=get_draft(con,user,draft_id,'report_print')
            if row['completed_at'] or data.get('version')!=row['version']: fail(409,'工单版本已改变，请重新打印')
            con.execute('UPDATE jy_drafts SET printed_version=version WHERE id=%s',(row['id'],))
            audit(con,user,'work.print_requested',1,str(row['id']),after={'version':row['version']})
            return {'ok':True,'version':row['version']}

    @app.post('/api/work-drafts/{draft_id}/discard')
    async def discard_draft(draft_id: str, request: Request):
        await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con); row=get_draft(con,user,draft_id,'draft_edit')
            if row['completed_at']: fail(409,'工单已确定，不能撤销草稿')
            con.execute('DELETE FROM jy_drafts WHERE id=%s',(row['id'],))
            audit(con,user,'work.draft.discard',1,str(row['id']),before={'rows':row['payload']['rows']})
        return {'ok':True}

    @app.post('/api/work-drafts/{draft_id}/confirm')
    async def confirm_draft(draft_id: str, request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con); row=get_draft(con,user,draft_id,'confirm_work')
            if row['completed_at']: return {'ids':row['committed_ids'],'alreadyConfirmed':True}
            if data.get('version')!=row['version']: fail(409,'工单版本已改变，请重新核对')
            rows=row['payload']['rows']
            if rows and row['printed_version']!=row['version']: fail(409,'请先打印当前版本，再核对并确定')
            work_ids=[]; confirmation_day=dt.datetime.now(UTC7).strftime('%Y/%-m/%-d')
            for position,entry in enumerate(rows):
                sale=record_by_id(con,entry['sourceRecordId'],0); require(con,user,0,'generate_work',sale)
                if str(sale['values_json'][0]).strip() in ['关闭','已关闭','已完成']:
                    fail(409,'销售订单已关闭或完成，不能继续确定工单')
                values=entry['values'][1:]; sid=str(values[12])
                if number(values[8])<=0: fail(400,'工单数量须大于0')
                remaining=remaining_quantity(con,sale['values_json'])
                if Decimal(str(values[8]).replace(',','').replace('，','').strip())>remaining: fail(409,'本次工单数量超过剩余可下达数量，请重新生成或调整')
                log=str(values[13])+confirmation_day+'：'+quantity_text(values[8])
                work=insert_record(con,user,1,values,entry['values'][0],meta={'printHistory':{'sourceId':sid,'entry':log},'documentNo':row['payload']['documentNo'],'preparer':row['payload'].get('preparer',''),'documentRow':position},team_id=row['team_id'],action='work.confirm')
                work_ids.append(str(work['id']))
                v=sale['values_json'].copy(); previous=str(v[26] or '').strip()
                log=str(values[13])+confirmation_day+'：'+quantity_text(values[8])
                v[26]=previous+'\n'+log if previous else log
                con.execute('UPDATE jy_records SET values_json=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(v),sale['id']))
                audit(con,user,'sales.work_print_confirmed',0,str(sale['id']),before={'history':previous},after={'history':v[26],'workId':str(work['id'])})
            con.execute('UPDATE jy_drafts SET completed_at=now(),committed_ids=%s WHERE id=%s',(Jsonb(work_ids),row['id']))
            audit(con,user,'work.draft.confirm',1,str(row['id']),after={'workIds':work_ids,'version':row['version']})
            return {'ids':work_ids,'alreadyConfirmed':False}

    @app.post('/api/work-orders/closure')
    async def change_work_closure(request: Request):
        data=await body(request)
        if type(data.get('reopen')) is not bool:fail(400,'工单操作无效')
        entries=data.get('records')
        if not isinstance(entries,list) or not 1<=len(entries)<=50000:fail(400,'请先勾选生产工单')
        action='reopen_order' if data['reopen'] else 'close_order'
        with store.connect(write=True) as con:
            user,_=current_user(request,con);require(con,user,1,action)
            request_id=uid(data['requestId']) if data.get('requestId') else None
            signature=hashlib.sha256(canonical(data).encode()).hexdigest()
            prior=con.execute('SELECT * FROM jy_requests WHERE id=%s',(request_id,)).fetchone() if request_id else None
            if prior:
                if str(prior['actor_id'])!=str(user['id']) or prior['signature']!=signature:fail(409,'保存请求标识已使用')
                current=[]
                for record in prior['response_json']['records']:
                    row=record_by_id(con,record['id'],1);require(con,user,1,action,row);current.append(public_record(row))
                return prior['response_json']|{'records':current}
            seen=set();output=[];changed=skipped=0
            for entry in entries:
                if not isinstance(entry,dict):fail(400,'工单记录无效')
                row=record_by_id(con,entry.get('id'),1);require(con,user,1,action,row)
                if str(row['id']) in seen:fail(400,'勾选工单重复')
                seen.add(str(row['id']))
                if entry.get('version')!=row['version']:fail(409,'工单已被他人修改，请重新载入后再操作')
                derived=work_state(row['values_json'],row['meta'].get('workStatus'))
                target='审核' if data['reopen'] else '关闭'
                if data['reopen'] and derived['workOwing']=='0':
                    skipped+=1;output.append(public_record(row));continue
                if derived['workStatus']==target:
                    output.append(public_record(row));continue
                metadata={**row['meta'],**derived,'workStatus':target}
                con.execute('UPDATE jy_records SET meta=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(metadata),row['id']))
                audit(con,user,'work.reopen' if data['reopen'] else 'work.close',1,str(row['id']),before={'status':derived['workStatus']},after={'status':target})
                changed+=1;output.append(public_record(record_by_id(con,row['id'],1)))
            result={'records':output,'changed':changed,'skippedCompleted':skipped}
            if request_id:con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)',(request_id,user['id'],signature,Jsonb(result)))
            return result

    @app.post('/api/work-orders/print-document')
    async def print_document(request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con);require(con,user,1,'report_print')
            document_no=text(data.get('documentNo'),'工单号',200)
            rows=con.execute("SELECT * FROM jy_records WHERE table_id=1 AND btrim(values_json->>14)=%s ORDER BY CASE WHEN meta->>'documentRow' ~ '^[0-9]+$' THEN (meta->>'documentRow')::bigint END NULLS LAST,created_at,id",(document_no,)).fetchall()
            if not rows:fail(404,'未找到该工单号对应的明细')
            for row in rows:require(con,user,1,'report_print',row)
            preparers={row['meta'].get('preparer') for row in rows if row['meta'].get('preparer')}
            audit(con,user,'work.document.print_requested' if data.get('phase')=='print' else 'work.document.preview',1,after={'documentNo':document_no,'ids':[str(row['id']) for row in rows]})
            return {'records':[public_record(row) for row in rows],'preparer':next(iter(preparers)) if len(preparers)==1 else ''}

    @app.post('/api/work-orders/generate-reports')
    async def generate_reports(request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con)
            ids=data.get('ids',[])
            if not isinstance(ids,list) or not ids: fail(400,'请先选择生产工单')
            output=[]
            for record_id in set(ids):
                work=record_by_id(con,record_id,1); require(con,user,1,'generate_report',work)
                v=work['values_json']; sid=str(v[12])
                if con.execute("SELECT 1 FROM jy_records WHERE table_id=2 AND meta->>'sourceWorkId'=%s LIMIT 1",(str(work['id']),)).fetchone(): continue
                values=[dt.datetime.now(UTC7).strftime('%Y-%m-%d'),v[2],v[5],v[8],v[1],0,v[10],'','','','',v[11],sid,dt.datetime.now(dt.timezone.utc).isoformat(),'','',v[13],v[14] or '']
                created=insert_record(con,user,2,values,meta={'sourceWorkId':str(work['id'])},team_id=work['team_id'],action='work.generate_report')
                output.append(str(created['id']))
            return {'ids':output}

    @app.post('/api/scan/submit')
    async def submit_scan(request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con); ids=data.get('ids',[])
            if not isinstance(ids,list) or not 1<=len(ids)<=200: fail(400,'每次提交1至200条扫码记录')
            if any(not isinstance(value,str) for value in ids) or (data.get('versions') is not None and not isinstance(data['versions'],dict)): fail(400,'扫码记录参数无效')
            accepted=[]; now=dt.datetime.now(dt.timezone.utc).isoformat()
            for record_id in sorted(set(ids)):
                row=con.execute('SELECT * FROM jy_records WHERE id=%s AND table_id=8 FOR UPDATE',(uid(record_id),)).fetchone()
                if not row: fail(404,'记录不存在或不可访问')
                require(con,user,8,'scan_submit',row)
                if row['meta'].get('productionReportId'):
                    accepted.append(str(row['id'])); continue
                if data.get('versions') is not None and data['versions'].get(str(row['id']))!=row['version']:
                    fail(409,'扫码记录已变化，请重新载入后确认')
                v=row['values_json']
                if not str(v[2]).strip() or not str(v[3]).strip(): fail(400,'请先填写工序和班组')
                try:
                    quantity=Decimal(str(v[8]).replace(',','').replace('，','').strip())
                    if not quantity.is_finite() or quantity<0: raise InvalidOperation()
                except (InvalidOperation,ValueError): fail(400,'数量无效')
                values=[v[1],v[4],v[6],'',v[3],v[8],row['meta'].get('unit',''),'','','','',v[9],v[11],v[0],'','',v[2],v[10]]
                report=insert_record(con,user,2,values,meta={'sourceScanId':str(row['id'])},team_id=row['team_id'],action='scan.generate_report')
                con.execute('UPDATE jy_records SET owner_id=%s,department=%s WHERE id=%s',(row['owner_id'],row['department'],report['id']))
                meta={**row['meta'],'submittedAt':row['meta'].get('submittedAt') or now,'reviewStatus':'已确认','productionReportId':str(report['id'])}
                con.execute('UPDATE jy_records SET meta=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(meta),row['id']))
                audit(con,user,'scan.submit',8,str(row['id']),after={'submittedAt':meta['submittedAt'],'productionReportId':str(report['id'])})
                accepted.append(str(row['id']))
            return {'acceptedIds':accepted,'submittedAt':now}

    @app.post('/api/sales/import')
    async def upload_sales(request: Request):
        data=await body(request)
        source_fields=CATALOG['3']['fields']; sales_fields=CATALOG['0']['fields']
        incoming=data.get('rows')
        if not isinstance(incoming,list) or not 1<=len(incoming)<=50000: fail(400,'上传记录数量无效')
        source_index=source_fields.index('订单子表ID'); lookup={}; blank=0
        for values in incoming:
            if not isinstance(values,list) or len(values)!=len(source_fields): fail(400,'上传字段不匹配')
            for value in values:
                if type(value) not in (str,int,float) or (isinstance(value,str) and len(value)>16384): fail(400,'上传单元格无效')
            sid=str(values[source_index]).strip()
            if not sid: blank+=1; continue
            if sid in lookup: fail(409,'上传订单子表ID重复：'+sid)
            lookup[sid]=values
        aliases={'订单数量':'数量','客户交期':'预发货日期','单位':'主计量单位'}
        mapping=[('数量','订单数量'),('累计发货数量','累计发货数量'),('未发货数量','未发货数量'),('预发货日期','客户交期'),('生产工艺','生产工艺')]
        with store.connect(write=True) as con:
            user,_=current_user(request,con); require(con,user,0,'import')
            existing=con.execute('SELECT * FROM jy_records WHERE table_id=0').fetchall(); by_id={}
            for row in existing:
                sid=str(row['values_json'][21]).strip()
                if sid and sid in by_id: fail(409,'销售订单ID重复，请先核对：'+sid)
                if sid: by_id[sid]=row
            added=matched=updated=fields=closed=0
            for sid,source in lookup.items():
                prior=by_id.get(sid)
                if prior:
                    require(con,user,0,'import',prior); require(con,user,0,'update',prior)
                    values=prior['values_json'].copy(); changed=0; matched+=1
                    for src,dst in mapping:
                        value=source[source_fields.index(src)]; index=sales_fields.index(dst)
                        if str(values[index])!=str(value): values[index]=value; changed+=1
                    fields+=changed; updated+=bool(changed)
                else:
                    require(con,user,0,'create')
                    # Imported sales rows inherit the server's authenticated owner/department.
                    values=[source[source_fields.index(aliases.get(name,name))] if aliases.get(name,name) in source_fields else '' for name in sales_fields]
                    values[26]=''; added+=1
                remaining=str(values[16]).replace(',','').strip()
                if remaining and number(remaining)==0 and str(values[0]).strip()!='关闭': values[0]='关闭';closed+=1
                if prior:
                    if values!=prior['values_json']:
                        con.execute('UPDATE jy_records SET values_json=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(values),prior['id']))
                        audit(con,user,'sales.import.update',0,str(prior['id']),before=public_record(prior),after={'values':values})
                else:
                    insert_record(con,user,0,values,action='sales.import.create')
            # Match the established rule for visible, authorized existing zero-balance orders.
            for prior in existing:
                if str(prior['values_json'][21]).strip() in lookup: continue
                if not in_scope(user,prior,scopes(con,user,0,'view')): continue
                if not in_scope(user,prior,scopes(con,user,0,'import')) or not in_scope(user,prior,scopes(con,user,0,'update')): continue
                values=prior['values_json'].copy(); remaining=str(values[16]).replace(',','').strip()
                if remaining and number(remaining)==0 and str(values[0]).strip()!='关闭':
                    require(con,user,0,'import',prior);require(con,user,0,'update',prior)
                    values[0]='关闭';closed+=1
                    con.execute('UPDATE jy_records SET values_json=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(values),prior['id']))
                    audit(con,user,'sales.import.close_zero',0,str(prior['id']),before=public_record(prior),after={'values':values})
            summary={'read':len(incoming),'blank':blank,'matched':matched,'added':added,'updated':updated,'fields':fields,'closed':closed}
            audit(con,user,'sales.import',0,after=summary)
            return summary

    @app.post('/api/scan/{record_id}/correct')
    async def correct_scan(record_id: str, request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con);row=record_by_id(con,record_id,8)
            require(con,user,8,'scan_correct',row)
            if not row['meta'].get('submittedAt'):fail(400,'未提交记录请通过正常编辑修改')
            if data.get('version')!=row['version']:fail(409,'报工记录已变化，请重新核对')
            reason=text(data.get('reason'),'更正原因',1000)
            values=validate_values(8,data.get('values'))
            if number(values[8])<0:fail(400,'报工数量不能为负数')
            if not values[2] or not values[3]:fail(400,'请保留有效工序和生产班组')
            team=resolve_team(con,user,8,values,'scan_correct',row)
            corrected_at=dt.datetime.now(dt.timezone.utc).isoformat()
            metadata={**row['meta'],'lastCorrection':{'actor':user['username'],'at':corrected_at,'reason':reason,'previousVersion':row['version']}}
            con.execute('UPDATE jy_records SET values_json=%s,meta=%s,team_id=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(values),Jsonb(metadata),team,row['id']))
            audit(con,user,'scan.correct',8,str(row['id']),before=public_record(row),after={'values':values,'reason':reason,'submittedAt':row['meta']['submittedAt']})
            return {'record':public_record(record_by_id(con,row['id']))}

    @app.get('/api/dashboard')
    def dashboard(request: Request):
        with store.connect() as con:
            user,_=current_user(request,con); allowed=require(con,user,7,'view')
            records=con.execute('SELECT * FROM jy_records WHERE table_id=2').fetchall()
            records=[r for r in records if in_scope(user,r,allowed)]
            units={}
            for row in records:
                v=row['values_json']; unit=str(v[6] or '码'); bucket=units.setdefault(unit,{'total':0,'hours':0,'count':0,'daily':{},'groups':{}})
                def numeric(value):
                    try: return float(str(value).replace(',','') or 0)
                    except ValueError: return 0
                quantity=numeric(v[5]); day=str(v[0])[:10]; group=str(v[16] or '未注明')
                bucket['total']+=quantity;bucket['hours']+=numeric(v[8]);bucket['count']+=1
                bucket['daily'][day]=bucket['daily'].get(day,0)+quantity
                bucket['groups'][group]=bucket['groups'].get(group,0)+quantity
            return {'units':units}

    @app.post('/api/inventory/generate-work')
    async def inventory_work(request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            user,_=current_user(request,con); ids=data.get('ids',[])
            if not isinstance(ids,list) or not ids: fail(400,'请先选择库存记录')
            output=[]
            for record_id in set(ids):
                inventory=record_by_id(con,record_id,5);require(con,user,5,'generate_work',inventory)
                source=str(inventory['id']);v=inventory['values_json']
                if con.execute("SELECT 1 FROM jy_records WHERE table_id=1 AND meta->>'sourceInventoryId'=%s LIMIT 1",(source,)).fetchone(): continue
                if number(v[4])<=0: fail(400,'补产数量须大于0')
                values=[stamp(),'','','','',v[0],'',v[3],v[4],0,v[6],'库存补产：'+str(v[2]),'INV-'+str(v[2]),'']
                work=insert_record(con,user,1,values,meta={'sourceInventoryId':source},action='inventory.generate_work')
                output.append(str(work['id']))
            return {'ids':output}

    def migration_preview(data):
        tables=data.get('tables'); information=data.get('information',{}); scan_meta=data.get('scanMeta',[])
        if not isinstance(tables,list) or len(tables)!=10 or not isinstance(information,dict) or not isinstance(scan_meta,list): fail(400,'迁移文件格式无效')
        counts,conflicts,warnings={},[],[]
        if tables[3]:warnings.append('临时表中转记录仅保留在原备份，不作为正式业务数据迁入；请先核对原系统上传结果')
        for table in BUSINESS_TABLES:
            rows=tables[table]
            if not isinstance(rows,list) or len(rows)>100000: fail(400,'迁移记录数量无效')
            counts[str(table)]=len(rows); seen=set()
            for index,values in enumerate(rows):
                validate_values(table,values)
                if table in (0,9):
                    value=str(values[{0:21,1:12,9:2}[table]]).strip()
                    if value and value in seen: conflicts.append({'table':table,'row':index+1,'value':value,'message':'标识或班组名称重复'})
                    if value: seen.add(value)
                if table==8 and index>=len(scan_meta): warnings.append('部分扫码记录缺少旧状态，按未提交迁入')
        return {'counts':counts,'conflicts':conflicts,'warnings':list(set(warnings)),
                'digest':hashlib.sha256(canonical(data).encode()).hexdigest()}

    @app.post('/api/admin/migration/preview')
    async def preview(request: Request):
        data=await body(request)
        with store.connect() as con:
            user,_=current_user(request,con);administrator(con,user)
            return migration_preview(data)

    @app.post('/api/admin/migration/commit')
    async def migrate(request: Request):
        request_data=await body(request); data=request_data.get('data',{})
        result=migration_preview(data)
        if result['conflicts'] or request_data.get('digest')!=result['digest']: fail(409,'迁移存在冲突或核对结果已改变')
        with store.connect(write=True) as con:
            user,_=current_user(request,con);administrator(con,user)
            prior=con.execute('SELECT * FROM jy_migrations WHERE digest=%s',(result['digest'],)).fetchone()
            if prior: return {'counts':prior['counts'],'alreadyImported':True}
            if con.execute('SELECT 1 FROM jy_records LIMIT 1').fetchone(): fail(409,'后台已有正式数据，不能覆盖迁入；请先核对基准数据')
            tables=data['tables']; teams={}
            for values in tables[9]:
                record=insert_record(con,user,9,values,action='migration.record');teams[str(values[2]).strip()]=str(record['id'])
            for table in [t for t in BUSINESS_TABLES if t!=9]:
                info=data.get('information',{}).get(str(table),{})
                for index,values in enumerate(tables[table]):
                    identity=(str(values[21]) if values[21] else ' / '.join(str(values[i]) for i in [5,6,8,10])) if table==0 else str(values[12]) if table==1 else ''
                    metadata={}
                    if table==8:
                        old=data.get('scanMeta',[])[index] if index<len(data.get('scanMeta',[])) else {}
                        metadata={k:old[k] for k in ['unit','reviewStatus','submittedAt'] if k in old}
                        metadata['reviewStatus']='已确认' if metadata.get('submittedAt') else metadata.get('reviewStatus','草稿')
                    if table==1:
                        identities=data.get('workRowIdentities',[])
                        prior=identities[index] if index<len(identities) else {}
                        if prior.get('status') in ['审核','关闭','已关闭']: metadata['workStatus']='关闭' if prior['status'] in ['关闭','已关闭'] else '审核'
                        links=data.get('workPrintLinks',{})
                        link=links.get(prior.get('key')) if isinstance(links,dict) and prior.get('signature')==json.dumps(values,ensure_ascii=False,separators=(',',':')) else None
                        if isinstance(link,dict) and isinstance(link.get('entry'),str) and isinstance(link.get('sourceId'),str):
                            metadata['printHistory']={'sourceId':link['sourceId'],'entry':link['entry']}
                            if isinstance(link.get('documentNo'),str): metadata['documentNo']=link['documentNo']
                            if isinstance(link.get('preparer'),str): metadata['preparer']=link['preparer']
                            if type(link.get('documentRow')) is int and link['documentRow']>=0: metadata['documentRow']=link['documentRow']
                    team=teams.get(str(values[{1:1,2:4,8:3}[table]]).strip()) if table in [1,2,8] else None
                    insert_record(con,user,table,validate_values(table,values),info.get((data.get('workRowIdentities',[])[index].get('key') if table==1 and index<len(data.get('workRowIdentities',[])) and data['workRowIdentities'][index].get('signature')==json.dumps(values,ensure_ascii=False,separators=(',',':')) else identity),''),metadata,team,action='migration.record')
            migration_id=str(uuid.uuid4())
            con.execute('INSERT INTO jy_migrations(id,actor_id,source_label,digest,counts) VALUES(%s,%s,%s,%s,%s)',
                        (migration_id,user['id'],text(data.get('sourceLabel','主数据'),'来源',200),result['digest'],Jsonb(result['counts'])))
            audit(con,user,'migration.commit',record_id=migration_id,after=result)
            return {'counts':result['counts'],'alreadyImported':False}

    @app.post('/api/admin/ownership')
    async def ownership(request: Request):
        data=await body(request)
        with store.connect(write=True) as con:
            actor,_=current_user(request,con);administrator(con,actor)
            owner=con.execute('SELECT * FROM jy_users WHERE id=%s AND enabled=true',(uid(data.get('ownerId')),)).fetchone()
            if not owner: fail(400,'归属用户不存在或已停用')
            team_id=uid(data['teamId']) if data.get('teamId') else None
            team=record_by_id(con,team_id,9) if team_id else None
            for record_id in data.get('ids',[]):
                row=record_by_id(con,record_id);values=row['values_json'].copy()
                if team and row['table_id'] in [1,2,8]: values[{1:1,2:4,8:3}[row['table_id']]]=team['values_json'][2]
                con.execute('UPDATE jy_records SET owner_id=%s,department=%s,team_id=%s,values_json=%s,version=version+1,updated_at=now() WHERE id=%s',
                            (owner['id'],owner['department'],team_id,Jsonb(values),row['id']))
                audit(con,actor,'record.assign',row['table_id'],str(row['id']),before=public_record(row),after={'ownerId':str(owner['id']),'teamId':team_id})
        return {'ok':True}
