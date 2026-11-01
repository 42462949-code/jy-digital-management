"""Atomic stock-to-voucher transfer; source quantities are consumed once."""
import uuid
from decimal import localcontext
from fastapi import Request
from psycopg.types.json import Jsonb
from .db import audit,canonical,public_record,in_scope,scopes
from .business_rules import decimal,text,date,stamp,inventory_key,refresh_derived,key

TYPES=['采购入库','生产领料','产品入库','其它入库','盘盈入库','采购退货','生产退料','销售出库','其它出库','盘亏出库']


def register_inventory_workflows(app,store):
    from .api import body,current_user,require,record_by_id,uid,fail,insert_record
    @app.post('/api/inventory/post-voucher')
    async def post(request:Request):
        import hashlib
        data=await body(request);signature=hashlib.sha256(canonical(data).encode()).hexdigest()
        with store.connect(write=True) as con:
            user,_=current_user(request,con);require(con,user,12,'generate_inventory');request_id=uid(data.get('requestId'))
            prior=con.execute('SELECT * FROM jy_requests WHERE id=%s',(request_id,)).fetchone()
            if prior:
                if str(prior['actor_id'])!=str(user['id']) or prior['signature']!=signature:fail(409,'请求标识已使用')
                return prior['response_json']
            records=data.get('records',[])
            if not isinstance(records,list) or not 1<=len(records)<=50000:fail(400,'请先在信息录入列填写数量')
            kind=data.get('type');partner=str(data.get('partner','')).strip();warehouse=str(data.get('warehouse','')).strip();note=str(data.get('note',''))
            try:day=date(data.get('date'))
            except ValueError as error:fail(400,str(error))
            if kind not in TYPES or not partner or not warehouse:fail(400,'日期、单据类型、供应商名称&出入库部门、仓库名称为必填项')
            if max(len(partner),len(warehouse),len(note))>16384:fail(400,'单据内容过长')
            counts={}
            for row in con.execute('SELECT values_json FROM jy_records WHERE table_id=12').fetchall():
                k=inventory_key(row['values_json']);counts[k]=counts.get(k,0)+1
            existing_ledger=con.execute('SELECT values_json FROM jy_records WHERE table_id=13').fetchall()
            prior_keys={inventory_key(r['values_json'],True) for r in existing_ledger}
            entries=[];seen=set()
            for entry in records:
                row=record_by_id(con,entry.get('id'),12);require(con,user,12,'generate_inventory',row)
                if row['id'] in seen:fail(400,'库存行重复')
                seen.add(row['id']);values=row['values_json']
                if entry.get('version')!=row['version'] or str(entry.get('information',''))!=str(values[1]):fail(409,'库存录入已改变，请刷新核对')
                try:
                    amount=decimal(values[1])
                    if amount<=0:raise ValueError()
                except ValueError:fail(400,'信息录入必须为大于0的数量')
                if counts[inventory_key(values)]>1:fail(409,'物品有重复库存记录，请先核对删除重复项')
                if key([values[8]])!=key([warehouse]):fail(400,'请选择与本次物品一致的仓库')
                entries.append((row,amount))
            inbound=kind in ['采购入库','产品入库','其它入库','盘盈入库','采购退货'];reverse=kind in ['采购退货','生产退料'];document=str(data.get('documentNo','')).strip()
            if document:
                if len(document)>200:fail(400,'单据编号过长')
                if con.execute('SELECT 1 FROM jy_records WHERE table_id=13 AND values_json->>1=%s',(document,)).fetchone():fail(409,'单据编号已存在')
            else:
                import re
                existing=[int(str(r['values_json'][1]).rsplit('-',1)[1]) for r in con.execute('SELECT values_json FROM jy_records WHERE table_id=13').fetchall() if re.fullmatch(r'(IN|OUT)-'+day.replace('-','')+r'-[0-9]+',str(r['values_json'][1]))]
                if existing:con.execute("INSERT INTO jy_document_sequences(day,last_value) VALUES(%s,%s) ON CONFLICT(day) DO UPDATE SET last_value=GREATEST(jy_document_sequences.last_value,excluded.last_value)",('INV-'+day,max(existing)))
                seq=con.execute("INSERT INTO jy_document_sequences(day,last_value) VALUES(%s,1) ON CONFLICT(day) DO UPDATE SET last_value=jy_document_sequences.last_value+1 RETURNING last_value",('INV-'+day,)).fetchone()['last_value']
                document=('IN' if inbound else 'OUT')+'-'+day.replace('-','')+'-'+str(seq).zfill(6)
            output=[];ids=[]
            with localcontext() as context:
                context.prec=180
                for row,quantity in entries:
                    v=row['values_json'];quantity=-quantity if reverse else quantity
                    values=[day,document,kind,partner,'',v[2],v[3],v[4],v[5],v[6],v[7],warehouse,'0' if inventory_key(v) in prior_keys else text(decimal(v[9],True)),text(quantity) if inbound else '0','0' if inbound else text(quantity),'',note,stamp()]
                    ledger=insert_record(con,user,13,values,meta={'sourceStockId':str(row['id']),'voucherRequest':request_id},action='inventory.post_voucher');ids.append(str(ledger['id']))
                    stock=v.copy();stock[1]=''
                    con.execute('UPDATE jy_records SET values_json=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(stock),row['id']))
                    audit(con,user,'inventory.consume_quantity',12,str(row['id']),before=v,after={'document':document,'quantity':text(quantity)})
                    output.append(public_record(record_by_id(con,row['id'],12)))
                    if in_scope(user,ledger,scopes(con,user,13,'view')):output.append(public_record(ledger))
            output=refresh_derived(con,user,output);result={'records':output,'ids':ids,'documentNo':document}
            con.execute('INSERT INTO jy_requests(id,actor_id,signature,response_json) VALUES(%s,%s,%s,%s)',(request_id,user['id'],signature,Jsonb(result)))
            return result
