"""Exact-decimal derived fields and authoritative business-row metadata."""
import datetime as dt
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, localcontext

from .db import UTC7


def decimal(value, blank=False):
    s=re.sub(r'[,，\s]','',str(value if value is not None else ''))
    if not s and blank:return Decimal(0)
    if len(s)>90 or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)',s):raise ValueError('请输入有效数字')
    try:
        value=Decimal(s)
        if not value.is_finite() or value.as_tuple().exponent < -30:raise ValueError('数字或小数位无效')
        return value
    except InvalidOperation:raise ValueError('请输入有效数字')


def text(value):
    value=format(value,'f')
    if '.' in value:value=value.rstrip('0').rstrip('.')
    return '0' if value in ('-0','') else value


def date(value):
    match=re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:$|[ T])',str(value).strip())
    if not match:raise ValueError('请选择有效生产日期')
    try:return dt.date(*map(int,match.groups())).isoformat()
    except ValueError:raise ValueError('请选择有效生产日期')


def stamp(now=None):return (now or dt.datetime.now(UTC7)).astimezone(UTC7).strftime('%Y-%m-%d %H:%M:%S')


def key(values):
    normalized=[re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(v if v is not None else ''))).strip().upper() for v in values]
    return json.dumps(normalized,ensure_ascii=False,separators=(',',':'))


def attendance(values,record_id,username,created=None,prior=None,department=None):
    values=values.copy()
    while len(values)<14:values.append('')
    values[0]=date(values[0])
    with localcontext() as context:
        context.prec=150
        hours=[decimal(values[i],True) for i in [2,3,4]]
        if any(h<0 for h in hours):raise ValueError('工时不能小于0')
        values[2:5]=[text(h) for h in hours]
        values[5]=text(sum(hours));values[6]=text(hours[0]+hours[1]*Decimal('1.5')+hours[2]*2)
        values[7]='3';values[8]=text(decimal(values[6])*3)
    values[10]=str(record_id);values[11]=department if department is not None else values[11]
    values[12]=prior[12] if prior else username;values[13]=prior[13] if prior else created or stamp()
    return values


def production(values):
    values=values.copy()
    while len(values)<22:values.append('')
    with localcontext() as context:
        context.prec=180
        if str(values[18]).strip():
            price=decimal(values[18])
            if price<0:raise ValueError('单价不能小于0')
            values[18]=text(price);values[19]=text(decimal(values[5])*price) if str(values[5]).strip() else ''
        else:values[18]='';values[19]=''
    return values


def price(values,record_id,line_no=None):
    values=values.copy();values[0]=str(line_no if line_no is not None else values[0])
    if any(not str(values[i]).strip() for i in [1,4,5]):raise ValueError('请填写客户简称、品名及加工明细、币别')
    value=decimal(values[6])
    if value<0:raise ValueError('单价不能小于0')
    values[6]=text(value)
    return values,key([values[1],values[2],values[3],values[4]])


def work_for_id(con,source_id,document=''):
    if not str(source_id).strip():return None
    rows=con.execute("SELECT * FROM jy_records WHERE table_id=1 AND btrim(values_json->>12)=%s",(str(source_id).strip(),)).fetchall()
    if document:
        exact=[r for r in rows if str(r['values_json'][14]).strip()==str(document).strip()]
        if exact:rows=exact
    return rows[0] if len(rows)==1 else None


def apply_price(con,values,meta=None,source=None,index=None):
    values=values.copy();legacy=len(values)<22
    while len(values)<22:values.append('')
    meta=dict(meta or {});source=source or (next((r for r in index['work'].get(str(values[12]).strip(),[]) if str(r['values_json'][14])==str(values[17])),None) if index is not None else work_for_id(con,values[12],values[17]))
    sales=(index['sales_id'].get(str(values[12]).strip(),[]) if index is not None else con.execute("SELECT * FROM jy_records WHERE table_id=0 AND btrim(values_json->>21)=%s",(str(values[12]).strip(),)).fetchall()) if str(values[12]).strip() else []
    if legacy:meta.setdefault('legacyOrderQuantity',values[3]);values[3]=''
    if source:
        v=source['values_json'];values[3]=v[4];values[20]=v[7];meta.update(material=v[6],spec=v[7],sourceWorkId=str(source['id']))
    if len(sales)==1:
        v=sales[0]['values_json'];values[3]=v[8];values[20]=v[9];meta.update(material=v[7],spec=v[9],sourceSaleId=str(sales[0]['id']))
    wanted=key([values[1],meta.get('material',''),values[20],values[2]])
    matches=index['sales_key'].get(wanted,[]) if index is not None else [r for r in con.execute('SELECT * FROM jy_records WHERE table_id=0').fetchall() if key([r['values_json'][i] for i in [4,7,9,10]])==wanted and len(r['values_json'])>=29]
    distinct={(str(r['values_json'][27]),str(r['values_json'][28])) for r in matches}
    if len(distinct)==1:
        currency,value=next(iter(distinct))
        if str(value).strip():values[18]=value;values[21]=currency;meta.update(currency=currency,priceStatus='已匹配')
    return production(values),meta


def sales_price(con,values,prices=None):
    values=values.copy()
    while len(values)<29:values.append('')
    wanted=key([values[i] for i in [4,7,9,10]])
    matches=(prices.get(wanted,[]) if prices is not None else con.execute("SELECT * FROM jy_records WHERE table_id=10 AND meta->>'priceStatus'='已审核' AND meta->>'priceKey'=%s",(wanted,)).fetchall())
    values[27:29]=[matches[0]['values_json'][5],matches[0]['values_json'][6]] if len(matches)==1 else ['','']
    return values


def inventory_key(values,ledger=False):return key([values[i] for i in ([6,7,8,9,10,11] if ledger else [3,4,5,6,7,8])])


def refresh_derived(con,user=None,output=None):
    from .db import public_record,in_scope,scopes
    merged={r['id']:r for r in (output or [])}
    totals={};prices={}
    for record in con.execute("SELECT * FROM jy_records WHERE table_id=10 AND meta->>'priceStatus'='已审核'").fetchall():prices.setdefault(record['meta']['priceKey'],[]).append(record)
    index=None
    with localcontext() as context:
        context.prec=180
        for record in con.execute('SELECT * FROM jy_records WHERE table_id=13').fetchall():
            v=record['values_json'];bucket=totals.setdefault(inventory_key(v,True),[Decimal(0),Decimal(0)])
            bucket[0]+=decimal(v[13],True);bucket[1]+=decimal(v[14],True)
        # Sales must be refreshed before production reads its price.
        for table in [0,2,4,12]:
            if table==2:
                index={'sales_id':{},'sales_key':{},'work':{}}
                for r in con.execute('SELECT * FROM jy_records WHERE table_id=ANY(%s)',([0,1],)).fetchall():
                    v=r['values_json']
                    if r['table_id']==0:index['sales_id'].setdefault(str(v[21]).strip(),[]).append(r);index['sales_key'].setdefault(key([v[i] for i in [4,7,9,10]]),[]).append(r)
                    else:index['work'].setdefault(str(v[12]).strip(),[]).append(r)
            for record in con.execute('SELECT * FROM jy_records WHERE table_id=%s',(table,)).fetchall():
                old=record['values_json'];values=old.copy();meta=record['meta']
                if table==0:values=sales_price(con,values,prices)
                elif table==2:values,meta=apply_price(con,values,meta,index=index)
                elif table==4:values=attendance(values,record['id'],'',prior=values)
                else:
                    inbound,outbound=totals.get(inventory_key(values),[Decimal(0),Decimal(0)])
                    values[10:13]=[text(inbound),text(outbound),text(decimal(values[9],True)+inbound-outbound)]
                if values!=old or meta!=record['meta']:
                    from psycopg.types.json import Jsonb
                    con.execute('UPDATE jy_records SET values_json=%s,meta=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(values),Jsonb(meta),record['id']))
                    record=con.execute('SELECT * FROM jy_records WHERE id=%s',(record['id'],)).fetchone()
                    if user and in_scope(user,record,scopes(con,user,table,'view')):merged[str(record['id'])]=public_record(record)
        # Replace earlier response versions for records updated twice in this transaction.
        for identifier,row in list(merged.items()):
            if not row.get('deleted'):
                current=con.execute('SELECT * FROM jy_records WHERE id=%s',(identifier,)).fetchone()
                if current:merged[identifier]=public_record(current)
    return list(merged.values())
