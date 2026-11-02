"""Administrator-managed, write-only-password account/node permission rows."""
import hashlib
import json
from pathlib import Path
import uuid
from fastapi import Request
from psycopg.types.json import Jsonb
from .db import CATALOG,ACTIONS,PASSWORDS,public_record,audit,canonical

MASK='****'
MASKS={MASK,'••••••'}
NODES={'表标签可看': 'view', '全部操作': '*', '查看': 'view', '新增': 'create', '修改': 'update', '保存': 'update', '确定': 'update', '删除': 'delete', '导入EXCEL': 'import', '导出EXCEL': 'export', '标签打印': 'label_print', '工单打印': 'report_print', '下推生成生产工单': 'generate_work', '下推生成生产报表': 'generate_report', '订单关闭': 'close_order', '关闭': 'close_order', '取消关闭': 'reopen_order', '新增班组': 'create', '审核': 'approve_price', '反审': 'unapprove_price', '下退生成出入库单据': 'generate_inventory', '启用摄像头': 'create', '清空扫码记录': 'delete', '目标设置': 'update', '编辑工单草稿': 'draft_edit', '确定工单': 'confirm_work', '扫码确认': 'scan_submit', '更正扫码报工': 'scan_correct', '库存调整': 'inventory_adjust', '单价和金额查看': 'financial_view', '下推生产工单': 'generate_work', '下推生产报表': 'generate_report', '关闭订单或工单': 'close_order', '审核单价': 'approve_price', '反审单价': 'unapprove_price', '生成出入库单据': 'generate_inventory', '下推生成出入库单据': 'generate_inventory', '启用设像头': 'create', '删除班组': 'delete', '密码是否见': 'password_view'}


def explicit_scopes(con,user,table,action):
    name=CATALOG.get(str(table),{}).get('name')
    rows=con.execute("SELECT values_json FROM jy_records WHERE table_id=14 AND values_json->>3=%s AND values_json->>6=%s",(user['username'],name)).fetchall()
    values=[row['values_json'] for row in rows]
    view_denied=any(NODES.get(v[7]) in ['view','*'] and v[8] in ['不允许','禁止'] for v in values)
    matching=[v for v in values if NODES.get(v[7]) in [action,'*']]
    if view_denied or any(v[8] in ['不允许','禁止'] for v in matching):return set()
    if any(v[8]=='允许' for v in matching):return {'all'}
    if action=='view' and any(v[8]=='允许' for v in values):return {'all'}
    return None


DEFAULT_TEMPLATE=json.loads(Path(__file__).with_name('access_template.json').read_text())

def permission_template(con):
    row=con.execute("SELECT payload FROM jy_business_settings WHERE name='access-permission-template'").fetchone()
    return row['payload'] if row else DEFAULT_TEMPLATE


def register_access_workflows(app,store):
    from .api import current_user,administrator,body,fail,uid,record_by_id
    def valid_template(rows):
        if not isinstance(rows,list) or not 1<=len(rows)<=10000:fail(400,'权限清单数量无效')
        seen=set();result=[]
        for pair in rows:
            if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(v,str) for v in pair):fail(400,'权限清单格式无效')
            table,node=(v.strip() for v in pair)
            if table not in [v['name'] for k,v in CATALOG.items() if k!='3'] or node not in NODES:fail(400,'清单表名或控制节点尚未接入系统')
            if (table,node) in seen:fail(400,'权限清单表名和控制节点重复')
            seen.add((table,node));result.append([table,node])
        return result

    @app.get('/api/access/template')
    async def get_template(request:Request):
        with store.connect() as con:
            actor,_=current_user(request,con);administrator(con,actor)
            return {'rows':permission_template(con)}

    @app.post('/api/access/template')
    async def update_template(request:Request):
        data=await body(request)
        with store.connect(write=True) as con:
            actor,_=current_user(request,con);administrator(con,actor)
            rows=valid_template(data.get('rows'))
            con.execute("INSERT INTO jy_business_settings(name,payload) VALUES('access-permission-template',%s) ON CONFLICT(name) DO UPDATE SET payload=EXCLUDED.payload",(Jsonb(rows),))
            audit(con,actor,'access.template.update',14,after={'items':len(rows)})
            return {'rows':rows}

    @app.get('/api/access/passwords')
    async def visible_passwords(request:Request):
        from .password_vault import password_view_allowed,read_password
        with store.connect(write=True) as con:
            actor,_=current_user(request,con);administrator(con,actor)
            if not password_view_allowed(con,actor):fail(403,'没有查看密码权限')
            names=[row['values_json'][3] for row in con.execute('SELECT values_json FROM jy_records WHERE table_id=14').fetchall()]
            accounts=con.execute('SELECT username,password_cipher FROM jy_users WHERE username=ANY(%s)',(names,)).fetchall() if names else []
            values={}
            for account in accounts:
                secret=read_password(account['username'],account['password_cipher'])
                values[account['username']]={'available':secret is not None,'value':secret if secret is not None else ''}
            audit(con,actor,'access.passwords.view',14,after={'accounts':len(values)})
            return {'passwords':values}

    @app.get('/api/access/user-password')
    async def user_password(request:Request,username:str):
        from .password_vault import read_password
        from fastapi.responses import JSONResponse
        with store.connect(write=True) as con:
            actor,_=current_user(request,con);administrator(con,actor)
            account=con.execute('SELECT * FROM jy_users WHERE username=%s',(username,)).fetchone()
            if not account or not con.execute('SELECT 1 FROM jy_records WHERE table_id=14 AND values_json->>3=%s',(username,)).fetchone():fail(404,'用户不存在')
            secret=read_password(username,account['password_cipher'])
            audit(con,actor,'access.user-password.view',14,after={'username':username})
            return JSONResponse({'password':secret,'accountVersion':account['version']},headers={'Cache-Control':'no-store'})

    @app.post('/api/access/rows')
    async def change(request:Request):
        data=await body(request);changes=data.get('changes',[])
        # Never persist password-containing request bodies or a fast password verifier.
        signed={**data,'changes':[{**c,'values':[('password supplied' if i==4 and v and v not in MASKS else '' if i==4 else v) for i,v in enumerate(c.get('values') or [])]} for c in changes if isinstance(c,dict)]}
        signature=hashlib.sha256(canonical(signed).encode()).hexdigest()
        with store.connect(write=True) as con:
            actor,actor_session=current_user(request,con);administrator(con,actor);request_id=uid(data.get('requestId'))
            prior=con.execute('SELECT * FROM jy_requests WHERE id=%s',(request_id,)).fetchone()
            if prior:
                if str(prior['actor_id'])!=str(actor['id']) or prior['signature']!=signature:fail(409,'请求标识已使用')
                supplied={str(c['values'][3]).strip():c['values'][4] for c in changes if isinstance(c.get('values'),list) and len(c['values'])==10 and ((c['values'][4] and c['values'][4] not in MASKS) or ((data.get('userEdit') or {}).get('passwordChanged') and c.get('id')==data['userEdit'].get('passwordRecordId')))}
                for name,password in supplied.items():
                    account=con.execute('SELECT password_hash FROM jy_users WHERE username=%s',(name,)).fetchone()
                    try:
                        if not account or not PASSWORDS.verify(account['password_hash'],password):raise ValueError()
                    except Exception:fail(409,'此请求已处理且密码内容已变化，请重新打开窗口核对')
                return prior['response_json']
            if not isinstance(changes,list) or not 1<=len(changes)<=10000:fail(400,'用户权限记录数量无效')
            user_edit=data.get('userEdit')
            if user_edit:
                name=user_edit.get('username')
                account=con.execute('SELECT * FROM jy_users WHERE username=%s FOR UPDATE',(name,)).fetchone()
                if not account or account['version']!=user_edit.get('accountVersion'):fail(409,'用户资料已变化，请重新打开窗口')
                records=con.execute('SELECT * FROM jy_records WHERE table_id=14 AND values_json->>3=%s FOR UPDATE',(name,)).fetchall()
                if {str(r['id']) for r in records}!=set(user_edit.get('recordIds',[])):fail(409,'用户权限清单已变化，请重新打开窗口')
                allowed={str(r['id']):r for r in records}
                if user_edit.get('passwordChanged') and user_edit.get('passwordRecordId') not in {c.get('id') for c in changes}:fail(400,'缺少密码修改记录')
                for change in changes:
                    prior_row=allowed.get(change.get('id'));values=change.get('values')
                    if not prior_row or change.get('delete') or not isinstance(values,list) or len(values)!=10:fail(400,'只能修改当前用户的资料及权限')
                    if any(values[i]!=prior_row['values_json'][i] for i in [0,3,6,7,9]):fail(400,'登录账号及权限节点不能修改')
                    if not str(values[1]).strip():fail(400,'部门为必填项')
                    if values[4] not in MASKS and not (user_edit.get('passwordChanged') and change['id']==user_edit.get('passwordRecordId')):fail(400,'密码修改标识无效')
                profiles={tuple(c['values'][i] for i in [1,2,5]) for c in changes}
                profile_changed=any(any(c['values'][i]!=allowed[c['id']]['values_json'][i] for i in [1,2,5]) for c in changes)
                if profile_changed and (len(profiles)!=1 or {c['id'] for c in changes}!=set(allowed)):fail(400,'用户资料必须同步更新全部权限记录')
            if data.get('newUser'):
                template=permission_template(con)
                if len(changes)!=len(template):fail(400,'新增用户必须填写完整权限清单')
                values=[c.get('values') for c in changes if isinstance(c,dict)]
                if len(values)!=len(changes) or any(not isinstance(v,list) or len(v)!=10 or any(not isinstance(x,str) for x in v) for v in values):fail(400,'新增用户字段无效')
                first=values[0];name=first[3].strip()
                if not name or not first[1].strip() or not first[4].strip() or first[4] in MASKS:fail(400,'用户姓名、密码、部门为必填项')
                if [[v[6],v[7]] for v in values]!=template or any(v[8] not in ['允许','不允许'] or any(v[i]!=first[i] for i in [1,2,3,5]) or c.get('delete') or c.get('version') not in [None,0] for v,c in zip(values,changes)):fail(400,'请完整填写当前清单的每项权限')
                if any(v[4] and v[4]!=first[4] for v in values[1:]):fail(400,'同一用户的密码不一致')
                con.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('access-new-user:'+name,))
                if con.execute('SELECT 1 FROM jy_users WHERE username=%s',(name,)).fetchone():fail(409,'该用户已存在，请使用修改功能')
                if any(con.execute('SELECT 1 FROM jy_records WHERE id=%s',(uid(c.get('id')),)).fetchone() for c in changes):fail(409,'新增用户不能修改已有权限')
            output=[];seen=set();affected=set()
            for entry in changes:
                identifier=uid(entry.get('id'))
                if identifier in seen:fail(400,'权限记录重复')
                seen.add(identifier);old=con.execute('SELECT * FROM jy_records WHERE id=%s'+(' FOR UPDATE' if data.get('permissionsOnly') or user_edit else ''),(identifier,)).fetchone()
                if old and old['table_id']!=14:fail(403,'记录不属于用户与权限表')
                if old and old['version']!=entry.get('version') or not old and entry.get('version') not in [0,None]:fail(409,'用户权限记录已变化，请重新载入')
                if data.get('permissionsOnly') and (entry.get('delete') or not old):fail(400,'权限修改只能更新已有记录的权限')
                if entry.get('delete'):
                    if not old:fail(409,'权限记录不存在')
                    affected.add(old['values_json'][3]);con.execute('DELETE FROM jy_records WHERE id=%s',(identifier,));output.append({'id':identifier,'table':14,'deleted':True});audit(con,actor,'access.delete',14,identifier,before=public_record(old));continue
                values=entry.get('values')
                if not isinstance(values,list) or len(values)!=10 or any(not isinstance(v,(str,int,float)) or (i!=4 and len(str(v))>16384) for i,v in enumerate(values)):fail(400,'用户权限字段无效')
                values=[str(v) for v in values];name=values[3].strip();table=values[6];node=values[7];permission=values[8];password=values[4]
                if not name or len(name)>80 or table not in [v['name'] for k,v in CATALOG.items() if k!='3'] or node not in NODES or permission not in ['允许','不允许']:fail(400,'请填写有效姓名、表名、控制节点和权限')
                if old and name!=old['values_json'][3]:fail(400,'已有权限记录的登录账号不能改名，请新增账号')
                if data.get('permissionsOnly'):
                    if any(values[i]!=old['values_json'][i] for i in range(10) if i!=8):fail(400,'此窗口只能修改权限列')
                    updated=old['values_json'].copy();updated[8]=permission
                    if updated!=old['values_json']:
                        con.execute('UPDATE jy_records SET values_json=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(updated),identifier))
                        audit(con,actor,'access.permission.update',14,identifier,before={'permission':old['values_json'][8]},after={'permission':permission})
                    output.append(public_record(record_by_id(con,identifier,14)));continue
                values[3]=name
                team=None
                if values[2]:
                    teams=con.execute('SELECT * FROM jy_records WHERE table_id=9 AND values_json->>2=%s AND values_json->>1=%s',(values[2],values[1])).fetchall()
                    if len(teams)==1:team=str(teams[0]['id'])
                if con.execute('SELECT 1 FROM jy_records WHERE table_id=14 AND id<>%s AND values_json->>3=%s AND values_json->>6=%s AND values_json->>7=%s',(identifier,name,table,node)).fetchone():fail(409,'同一用户、表名和控制节点不能重复')
                account=con.execute('SELECT * FROM jy_users WHERE username=%s',(name,)).fetchone();managed=not account or not account['role_ids']
                if (user_edit and user_edit.get('passwordChanged') and identifier==user_edit.get('passwordRecordId')) or (password and password not in MASKS) or not account:
                    encoded=PASSWORDS.hash(password if user_edit else '' if password in MASKS else password)
                else:encoded=None
                if not account:
                    user_id=str(uuid.uuid4());con.execute('INSERT INTO jy_users(id,username,name,department,team_ids,role_ids,password_hash,must_change_password) VALUES(%s,%s,%s,%s,%s,%s,%s,false)',(user_id,name,name,values[1],Jsonb([team] if team else []),Jsonb([]),encoded))
                else:
                    user_id=str(account['id']);con.execute('UPDATE jy_users SET department=%s,team_ids=%s,password_hash=COALESCE(%s,password_hash),must_change_password=CASE WHEN %s THEN false ELSE must_change_password END,enabled=CASE WHEN %s THEN enabled ELSE true END,version=version+1 WHERE id=%s',(values[1] if values[1] or values[2] else account['department'],Jsonb([team] if team else [] if values[1] else account['team_ids']),encoded,bool(encoded),bool(user_edit),user_id))
                    if encoded:
                        if user_edit and user_id==str(actor['id']):con.execute('DELETE FROM jy_sessions WHERE user_id=%s AND token_hash<>%s',(user_id,actor_session['token_hash']))
                        else:con.execute('DELETE FROM jy_sessions WHERE user_id=%s',(user_id,))
                if encoded:
                    from .password_vault import seal_password
                    con.execute('UPDATE jy_users SET password_cipher=%s WHERE id=%s',(seal_password(name,password if user_edit else '' if password in MASKS else password),user_id))
                values[0]=old['values_json'][0] if old else str(con.execute("SELECT nextval('jy_access_row_no') AS n").fetchone()['n']);values[4]=MASK;meta={'userId':user_id,'managedAccount':managed}
                if old:con.execute("UPDATE jy_records SET values_json=%s,meta=%s,version=version+1,updated_at=now() WHERE id=%s",(Jsonb(values),Jsonb(meta),identifier))
                else:con.execute('INSERT INTO jy_records(id,table_id,values_json,meta,owner_id,department) VALUES(%s,14,%s,%s,%s,%s)',(identifier,Jsonb(values),Jsonb(meta),actor['id'],actor['department']))
                output.append(public_record(record_by_id(con,identifier,14)));affected.add(name);audit(con,actor,'access.update' if old else 'access.create',14,identifier,after={'values':values,'changedPassword':bool(encoded)})
            for name in affected:
                account=con.execute('SELECT * FROM jy_users WHERE username=%s',(name,)).fetchone()
                if account and not account['role_ids'] and not con.execute('SELECT 1 FROM jy_records WHERE table_id=14 AND values_json->>3=%s',(name,)).fetchone():
                    con.execute('UPDATE jy_users SET enabled=false,version=version+1 WHERE id=%s',(account['id'],));con.execute('DELETE FROM jy_sessions WHERE user_id=%s',(account['id'],))
            result={'records':output};con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)',(request_id,actor['id'],signature,Jsonb(result)));return result
