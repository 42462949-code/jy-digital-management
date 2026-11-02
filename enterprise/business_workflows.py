"""Price approval, entered-quantity reports, and daily hourly-output snapshots."""
import datetime as dt
import hashlib
import uuid
from decimal import Decimal,localcontext

from fastapi import Request
from psycopg.types.json import Jsonb
from .db import UTC7,canonical,in_scope,public_record,scopes,audit
from .business_rules import date,decimal,text,stamp,key,apply_price
from .work_state import work_state


def now_local():return dt.datetime.now(UTC7)


def generate_work_reports(con,user,data):
    from .api import fail,require,record_by_id,insert_record,uid,resolve_team
    records=data.get('records',[])
    if not isinstance(records,list) or not 1<=len(records)<=2000:fail(400,'请先选择工单并录入生产数量')
    request_id=uid(data.get('requestId'));signature=hashlib.sha256(canonical(data).encode()).hexdigest()
    sources=[];seen=set()
    for item in records:
        if not isinstance(item,dict):fail(400,'工单参数无效')
        row=record_by_id(con,item.get('id'),1);require(con,user,1,'generate_report',row)
        if str(row['id']) in seen:fail(400,'工单重复')
        row=con.execute('SELECT * FROM jy_records WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
        seen.add(str(row['id']));sources.append((row,item))
    prior=con.execute('SELECT * FROM jy_requests WHERE id=%s',(request_id,)).fetchone()
    if prior:
        if str(prior['actor_id'])!=str(user['id']) or prior['signature']!=signature:fail(409,'请求标识已使用')
        return prior['response_json']
    is_draft=data.get('draft') is True
    if not is_draft:
        try:production_date=date(data.get('date',''))
        except ValueError as error:fail(400,str(error))
        department=data.get('department');team_id=uid(data.get('teamId'))
        team=record_by_id(con,team_id,9)
        if department not in ['贴合','泡棉'] or str(team['values_json'][1]).strip()!=department:fail(400,'部门与生产班组不对应')
        if 'all' not in scopes(con,user,1,'generate_report') and team_id not in user['team_ids']:fail(403,'不能向未分配的班组报工')
    output=[];ids=[]
    for row,item in sources:
        if item.get('version')!=row['version']:fail(409,'工单已变化，请重新载入')
        information=str(row['information']).strip()
        if not information:fail(400,'请先在“信息录入”列录入生产数量')
        if item.get('information')!=information:fail(409,'信息录入已变化，请重新核对')
        try:
            quantity=decimal(information)
            if quantity<=0:raise ValueError()
        except ValueError:fail(400,'请在“信息录入”列填写一个大于0的生产数量')
        if work_state(row['values_json'],row['meta'].get('workStatus'))['workStatus']=='关闭':fail(409,'已关闭工单不能下推生产报表')
        v=row['values_json']
        if is_draft:
            try:
                production_date=date(item.get('date',''));quantity=decimal(item.get('quantity',''))
                if quantity<=0:raise ValueError()
            except (ValueError,TypeError):fail(400,'请填写有效日期及大于0的生产数量')
            if any(not isinstance(item.get(k),str) or not item[k].strip() or len(item[k])>16384 for k in ['department','equipment']):fail(400,'请填写部门和设备')
            department=item['department'].strip();equipment=item['equipment'].strip()
            matches=con.execute('SELECT * FROM jy_records WHERE table_id=9 AND btrim(values_json->>2)=%s AND btrim(values_json->>1)=%s',(equipment,department)).fetchall()
            if len(matches)>1:fail(400,'部门与设备的基础资料存在重复')
            team_id=str(matches[0]['id']) if matches else row['team_id'] if department==v[13] else None
            if 'all' not in scopes(con,user,1,'generate_report') and (not matches or team_id not in user['team_ids']):fail(403,'不能向未分配的部门或设备报工')
        else:equipment=team['values_json'][2]
        values=[production_date,v[2],v[5],v[4],equipment,text(quantity),v[10],'','','','',v[11],v[12],stamp(),'','',department,v[14],'','',v[7],'']
        values,meta=apply_price(con,values,{'sourceWorkId':str(row['id'])},row)
        report=insert_record(con,user,2,values,meta=meta,team_id=team_id,action='work.generate_report');ids.append(str(report['id']))
        if is_draft:
            con.execute('UPDATE jy_records SET department=%s WHERE id=%s',(department,report['id']))
            report=record_by_id(con,report['id'],2)
        updated=v.copy()
        with localcontext() as context:
            context.prec=150;updated[9]=text(decimal(v[9],True)+quantity)
        metadata={**row['meta'],**work_state(updated,row['meta'].get('workStatus'))}
        con.execute("UPDATE jy_records SET values_json=%s,information='',meta=%s,version=version+1,updated_at=now() WHERE id=%s",(Jsonb(updated),Jsonb(metadata),row['id']))
        audit(con,user,'work.report_quantity',1,str(row['id']),before={'produced':v[9],'information':information},after={'produced':updated[9],'reportId':str(report['id'])})
        output.append(public_record(record_by_id(con,row['id'],1)))
        if in_scope(user,report,scopes(con,user,2,'view')):output.append(public_record(report))
    result={'ids':ids,'records':output}
    con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)',(request_id,user['id'],signature,Jsonb(result)))
    return result


def ensure_daily_snapshot(con,current=None):
    current=current or now_local();cutoff=(current.date()-dt.timedelta(days=1 if current.hour>=10 else 2)).isoformat()
    prior=con.execute('SELECT payload FROM jy_daily_business_snapshot WHERE cutoff=%s',(cutoff,)).fetchone()
    if prior:return prior['payload']
    grouped={}
    with localcontext() as context:
        context.prec=180
        for row in con.execute('SELECT * FROM jy_records WHERE table_id=ANY(%s)',([4,2],)).fetchall():
            v=row['values_json']
            try:day=date(v[0])
            except ValueError:continue
            if day>cutoff:continue
            group=(day,str(row['owner_id']),str(row['team_id']) if row['team_id'] else None,row['department'])
            bucket=grouped.setdefault(group,{'date':day,'owner_id':group[1],'team_id':group[2],'department':group[3],'hours':Decimal(0),'amount':Decimal(0),'missing':0})
            try:
                if row['table_id']==4:bucket['hours']+=decimal(v[5],True)
                elif len(v)>=20 and str(v[19]).strip():bucket['amount']+=decimal(v[19])
                else:bucket['missing']+=1
            except ValueError:continue
        payload={'cutoff':cutoff,'updatedAt':current.isoformat(),'groups':[{**v,'hours':text(v['hours']),'amount':text(v['amount'])} for v in grouped.values()]}
    con.execute('INSERT INTO jy_daily_business_snapshot(cutoff,payload) VALUES(%s,%s) ON CONFLICT(cutoff) DO NOTHING',(cutoff,Jsonb(payload)))
    return con.execute('SELECT payload FROM jy_daily_business_snapshot WHERE cutoff=%s',(cutoff,)).fetchone()['payload']


async def snapshot_worker(store):
    import asyncio
    while True:
        try:
            with store.connect(write=True) as con:ensure_daily_snapshot(con)
            current=now_local();next_update=dt.datetime.combine(current.date()+(dt.timedelta(days=1) if current.hour>=10 else dt.timedelta()),dt.time(10),tzinfo=UTC7)
            delay=max(1,(next_update-current).total_seconds())
        except Exception:
            delay=30
        await asyncio.sleep(delay)


def register_business_workflows(app,store):
    from .api import body,current_user,require,record_by_id,uid,fail

    @app.get('/api/references/report-teams')
    def report_teams(request:Request):
        with store.connect() as con:
            user,_=current_user(request,con);allowed=require(con,user,1,'generate_report')
            rows=con.execute('SELECT * FROM jy_records WHERE table_id=9 ORDER BY values_json->>2').fetchall()
            return {'teams':[{'id':str(row['id']),'name':str(row['values_json'][2]).strip(),'department':str(row['values_json'][1]).strip()} for row in rows if 'all' in allowed or str(row['id']) in user['team_ids']]}

    @app.post('/api/price-list/review')
    async def review(request:Request):
        data=await body(request);approve=data.get('approve')
        if type(approve) is not bool:fail(400,'审核参数无效')
        records=data.get('records',[])
        if not isinstance(records,list) or not 1<=len(records)<=50000:fail(400,'请先勾选单价记录')
        with store.connect(write=True) as con:
            user,_=current_user(request,con);operation='approve_price' if approve else 'unapprove_price';request_id=uid(data.get('requestId'));signature=hashlib.sha256(canonical(data).encode()).hexdigest();rows=[];seen=set()
            for item in records:
                if not isinstance(item,dict):fail(400,'单价参数无效')
                row=record_by_id(con,item.get('id'),10);require(con,user,10,operation,row)
                if str(row['id']) in seen:fail(400,'单价记录重复')
                seen.add(str(row['id']));rows.append((row,item))
            prior=con.execute('SELECT * FROM jy_requests WHERE id=%s',(request_id,)).fetchone()
            if prior:
                if str(prior['actor_id'])!=str(user['id']) or prior['signature']!=signature:fail(409,'请求标识已使用')
                return prior['response_json']
            for row,item in rows:
                if item.get('version')!=row['version']:fail(409,'单价已变化，请重新载入')
            if approve:
                approved=con.execute("SELECT * FROM jy_records WHERE table_id=10 AND meta->>'priceStatus'='已审核'").fetchall();keys={r['meta']['priceKey']:str(r['id']) for r in approved}
                for row,_ in rows:
                    price_key=row['meta'].get('priceKey') or key([row['values_json'][i] for i in [1,2,3,4]])
                    if price_key in keys and keys[price_key]!=str(row['id']):fail(409,'相同客户、代料品名、规格、品名及加工明细已有已审核单价，请先反审旧价')
                    keys[price_key]=str(row['id'])
            output=[];changed=0;target='已审核' if approve else '未审核'
            for row,_ in rows:
                if row['meta'].get('priceStatus','未审核')!=target:
                    meta={**row['meta'],'priceStatus':target,'reviewActor':user['username'],'reviewTime':stamp()}
                    con.execute('UPDATE jy_records SET meta=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(meta),row['id']));changed+=1
                    audit(con,user,'price.approve' if approve else 'price.unapprove',10,str(row['id']),after=meta)
                output.append(public_record(record_by_id(con,row['id'],10)))
            from .business_rules import refresh_derived
            output=refresh_derived(con,user,output)
            result={'records':output,'changed':changed};con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)',(request_id,user['id'],signature,Jsonb(result)))
            return result

    @app.get('/api/reports/hourly-output')
    def hourly(request:Request,month:str,action:str="view"):
        try:
            start=dt.date.fromisoformat(month+'-01')
        except ValueError:fail(400,'月份格式应为YYYY-MM')
        current=now_local();cutoff=current.date()-dt.timedelta(days=1 if current.hour>=10 else 2)
        with store.connect(write=True) as con:
            user,_=current_user(request,con)
            if action not in ['view','export']:fail(400,'统计操作无效')
            allowed=require(con,user,11,action)
            frozen=ensure_daily_snapshot(con,current);hours={};amounts={};missing=0
            with localcontext() as context:
                context.prec=180
                for row in con.execute('SELECT * FROM jy_records WHERE table_id=2').fetchall():
                    if not in_scope(user,row,allowed):continue
                    try:
                        day=date(row['values_json'][0])
                        if not day.startswith(month+'-') or day>frozen['cutoff']:continue
                        value=row['values_json'][19]
                        if not str(value).strip():missing+=1;continue
                        amounts[day]=amounts.get(day,Decimal(0))+decimal(value)
                    except ValueError:continue
                for row in con.execute('SELECT * FROM jy_records WHERE table_id=4').fetchall():
                    if not in_scope(user,row,allowed):continue
                    try:
                        day=date(row['values_json'][0])
                        if not day.startswith(month+'-') or day>frozen['cutoff']:continue
                        hours[day]=hours.get(day,Decimal(0))+decimal(row['values_json'][5],True)
                    except ValueError:continue
                payload={'hours':{k:text(v) for k,v in hours.items()},'amounts':{k:text(v) for k,v in amounts.items()},'missingPrices':missing,'cutoff':frozen['cutoff'],'updatedAt':current.isoformat()}
            preference=con.execute("SELECT payload FROM jy_business_settings WHERE name='hourly-targets'").fetchone()
            next_update=dt.datetime.combine(current.date()+(dt.timedelta(days=1) if current.hour>=10 else dt.timedelta()),dt.time(10),tzinfo=UTC7)
            return {**payload,'target':(preference['payload'].get(month,'35') if preference else '35'),'nextUpdate':next_update.isoformat()}

    @app.post('/api/reports/hourly-output/target')
    async def target(request:Request):
        data=await body(request)
        try:
            month=data.get('month','');dt.date.fromisoformat(month+'-01');value=decimal(data.get('target',''))
            if value<0:raise ValueError()
        except (ValueError,TypeError):fail(400,'请选择有效月份并填写不小于0的目标')
        with store.connect(write=True) as con:
            user,_=current_user(request,con);require(con,user,11,'update');prior=con.execute("SELECT payload FROM jy_business_settings WHERE name='hourly-targets'").fetchone();settings={**(prior['payload'] if prior else {}),month:text(value)}
            con.execute("INSERT INTO jy_business_settings(name,payload) VALUES('hourly-targets',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",(Jsonb(settings),))
            audit(con,user,'hourly.target',11,month,before=prior['payload'].get(month) if prior else None,after=text(value))
            return {'target':text(value)}
