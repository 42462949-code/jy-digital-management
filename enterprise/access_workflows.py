"""Administrator-managed, write-only-password account/node permission rows."""
import hashlib
import uuid
from fastapi import Request
from psycopg.types.json import Jsonb
from .db import CATALOG,ACTIONS,PASSWORDS,public_record,audit,canonical

MASK='••••••'
NODES={'表标签可看': 'view', '全部操作': '*', '查看': 'view', '新增': 'create', '修改': 'update', '保存': 'update', '确定': 'update', '删除': 'delete', '导入EXCEL': 'import', '导出EXCEL': 'export', '标签打印': 'label_print', '工单打印': 'report_print', '下推生成生产工单': 'generate_work', '下推生成生产报表': 'generate_report', '订单关闭': 'close_order', '关闭': 'close_order', '取消关闭': 'reopen_order', '新增班组': 'create', '审核': 'approve_price', '反审': 'unapprove_price', '下退生成出入库单据': 'generate_inventory', '启用摄像头': 'create', '清空扫码记录': 'delete', '目标设置': 'update', '编辑工单草稿': 'draft_edit', '确定工单': 'confirm_work', '扫码确认': 'scan_submit', '更正扫码报工': 'scan_correct', '库存调整': 'inventory_adjust', '单价和金额查看': 'financial_view', '下推生产工单': 'generate_work', '下推生产报表': 'generate_report', '关闭订单或工单': 'close_order', '审核单价': 'approve_price', '反审单价': 'unapprove_price', '生成出入库单据': 'generate_inventory', '下推生成出入库单据': 'generate_inventory', '启用设像头': 'create', '删除班组': 'delete'}


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


def register_access_workflows(app,store):
    from .api import current_user,administrator,body,fail,uid,record_by_id
    @app.post('/api/access/rows')
    async def change(request:Request):
        data=await body(request);changes=data.get('changes',[])
        # Never persist password-containing request bodies or a fast password verifier.
        signed={**data,'changes':[{**c,'values':[('password supplied' if i==4 and v and v!=MASK else '' if i==4 else v) for i,v in enumerate(c.get('values') or [])]} for c in changes if isinstance(c,dict)]}
        signature=hashlib.sha256(canonical(signed).encode()).hexdigest()
        with store.connect(write=True) as con:
            actor,_=current_user(request,con);administrator(con,actor);request_id=uid(data.get('requestId'))
            prior=con.execute('SELECT * FROM jy_requests WHERE id=%s',(request_id,)).fetchone()
            if prior:
                if str(prior['actor_id'])!=str(actor['id']) or prior['signature']!=signature:fail(409,'请求标识已使用')
                supplied={str(c['values'][3]).strip():c['values'][4] for c in changes if isinstance(c.get('values'),list) and len(c['values'])==10 and c['values'][4] and c['values'][4]!=MASK}
                for name,password in supplied.items():
                    account=con.execute('SELECT password_hash FROM jy_users WHERE username=%s',(name,)).fetchone()
                    try:
                        if not account or not PASSWORDS.verify(account['password_hash'],password):raise ValueError()
                    except Exception:fail(409,'此请求已处理且密码内容已变化，请重新打开窗口核对')
                return prior['response_json']
            if not isinstance(changes,list) or not 1<=len(changes)<=10000:fail(400,'用户权限记录数量无效')
            output=[];seen=set();affected=set()
            for entry in changes:
                identifier=uid(entry.get('id'))
                if identifier in seen:fail(400,'权限记录重复')
                seen.add(identifier);old=con.execute('SELECT * FROM jy_records WHERE id=%s',(identifier,)).fetchone()
                if old and old['table_id']!=14:fail(403,'记录不属于用户与权限表')
                if old and old['version']!=entry.get('version') or not old and entry.get('version') not in [0,None]:fail(409,'用户权限记录已变化，请重新载入')
                if entry.get('delete'):
                    if not old:fail(409,'权限记录不存在')
                    affected.add(old['values_json'][3]);con.execute('DELETE FROM jy_records WHERE id=%s',(identifier,));output.append({'id':identifier,'table':14,'deleted':True});audit(con,actor,'access.delete',14,identifier,before=public_record(old));continue
                values=entry.get('values')
                if not isinstance(values,list) or len(values)!=10 or any(not isinstance(v,(str,int,float)) or (i!=4 and len(str(v))>16384) for i,v in enumerate(values)):fail(400,'用户权限字段无效')
                values=[str(v) for v in values];name=values[3].strip();table=values[6];node=values[7];permission=values[8];password=values[4]
                if not name or len(name)>80 or table not in [v['name'] for k,v in CATALOG.items() if k!='3'] or node not in NODES or permission not in ['允许','不允许']:fail(400,'请填写有效姓名、表名、控制节点和权限')
                if old and name!=old['values_json'][3]:fail(400,'已有权限记录的登录账号不能改名，请新增账号')
                values[3]=name
                team=None
                if values[2]:
                    teams=con.execute('SELECT * FROM jy_records WHERE table_id=9 AND values_json->>2=%s AND values_json->>1=%s',(values[2],values[1])).fetchall()
                    if len(teams)==1:team=str(teams[0]['id'])
                if con.execute('SELECT 1 FROM jy_records WHERE table_id=14 AND id<>%s AND values_json->>3=%s AND values_json->>6=%s AND values_json->>7=%s',(identifier,name,table,node)).fetchone():fail(409,'同一用户、表名和控制节点不能重复')
                account=con.execute('SELECT * FROM jy_users WHERE username=%s',(name,)).fetchone();managed=not account or not account['role_ids']
                if (password and password!=MASK) or not account:
                    encoded=PASSWORDS.hash('' if password==MASK else password)
                else:encoded=None
                if not account:
                    user_id=str(uuid.uuid4());con.execute('INSERT INTO jy_users(id,username,name,department,team_ids,role_ids,password_hash,must_change_password) VALUES(%s,%s,%s,%s,%s,%s,%s,false)',(user_id,name,name,values[1],Jsonb([team] if team else []),Jsonb([]),encoded))
                else:
                    user_id=str(account['id']);con.execute('UPDATE jy_users SET department=%s,team_ids=%s,password_hash=COALESCE(%s,password_hash),must_change_password=CASE WHEN %s THEN false ELSE must_change_password END,enabled=true,version=version+1 WHERE id=%s',(values[1] if values[1] or values[2] else account['department'],Jsonb([team] if team else [] if values[1] else account['team_ids']),encoded,bool(encoded),user_id))
                    if encoded:con.execute('DELETE FROM jy_sessions WHERE user_id=%s',(user_id,))
                values[0]=old['values_json'][0] if old else str(con.execute("SELECT nextval('jy_access_row_no') AS n").fetchone()['n']);values[4]=MASK;meta={'userId':user_id,'managedAccount':managed}
                if old:con.execute("UPDATE jy_records SET values_json=%s,meta=%s,version=version+1,updated_at=now() WHERE id=%s",(Jsonb(values),Jsonb(meta),identifier))
                else:con.execute('INSERT INTO jy_records(id,table_id,values_json,meta,owner_id,department) VALUES(%s,14,%s,%s,%s,%s)',(identifier,Jsonb(values),Jsonb(meta),actor['id'],actor['department']))
                output.append(public_record(record_by_id(con,identifier,14)));affected.add(name);audit(con,actor,'access.update' if old else 'access.create',14,identifier,after={'values':values,'changedPassword':bool(encoded)})
            for name in affected:
                account=con.execute('SELECT * FROM jy_users WHERE username=%s',(name,)).fetchone()
                if account and not account['role_ids'] and not con.execute('SELECT 1 FROM jy_records WHERE table_id=14 AND values_json->>3=%s',(name,)).fetchone():
                    con.execute('UPDATE jy_users SET enabled=false,version=version+1 WHERE id=%s',(account['id'],));con.execute('DELETE FROM jy_sessions WHERE user_id=%s',(account['id'],))
            result={'records':output};con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)',(request_id,actor['id'],signature,Jsonb(result)));return result
