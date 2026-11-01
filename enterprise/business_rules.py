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
        if str(values[7]).strip():
            price=decimal(values[7])
            if price<0:raise ValueError('工时单价不能小于0')
            values[8]=text(decimal(values[6])*price)
        else:values[8]=''
    values[10]=str(record_id);values[11]=department if department is not None else values[11]
    values[12]=prior[12] if prior else username;values[13]=prior[13] if prior else created or stamp()
    return values


def production(values):
    values=values.copy()
    while len(values)<20:values.append('')
    with localcontext() as context:
        context.prec=180
        if str(values[18]).strip():
            price=decimal(values[18])
            if price<0:raise ValueError('单价不能小于0')
            values[18]=text(price);values[19]=text(decimal(values[5])*price) if str(values[5]).strip() else ''
        else:values[18]='';values[19]=''
    return values


def price(values,record_id):
    values=values.copy();values[0]=str(record_id)
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


def apply_price(con,values,meta=None,source=None):
    values=values.copy()
    while len(values)<20:values.append('')
    meta=dict(meta or {});source=source or work_for_id(con,values[12],values[17])
    if source:
        v=source['values_json'];meta.update(material=v[6],spec=v[7],sourceWorkId=str(source['id']))
    wanted=key([values[1],meta.get('material',''),meta.get('spec',''),values[2]])
    matches=con.execute("SELECT * FROM jy_records WHERE table_id=10 AND meta->>'priceStatus'='已审核' AND meta->>'priceKey'=%s",(wanted,)).fetchall()
    if len(matches)==1:
        chosen=matches[0];values[18]=chosen['values_json'][6]
        meta.update(priceId=str(chosen['id']),currency=chosen['values_json'][5],priceStatus='已匹配')
    else:values[18]='';meta['priceStatus']='待填写'
    return production(values),meta

