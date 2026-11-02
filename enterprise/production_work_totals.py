"""Reconcile edited/deleted production totals by document number AND order-line ID."""
from decimal import Decimal,localcontext
from psycopg.types.json import Jsonb
from .business_rules import decimal,text
from .db import audit,in_scope,scopes,public_record
from .work_state import work_state


def production_key(values,work=False):
    if len(values)<=(14 if work else 17):return None
    document=str(values[14 if work else 17] if values[14 if work else 17] is not None else '').strip();line=str(values[12] if values[12] is not None else '').strip()
    return (document,line) if document and line else None


def reconcile_production_work(con,user,keys):
    keys={k for k in keys if k};works=[]
    for document,line in sorted(keys):
        works.extend(con.execute("SELECT * FROM jy_records WHERE table_id=1 AND btrim(values_json->>14)=%s AND btrim(values_json->>12)=%s ORDER BY id FOR UPDATE",(document,line)).fetchall())
    if not works:return []
    totals={k:Decimal(0) for k in keys}
    with localcontext() as context:
        context.prec=180
        for report in con.execute('SELECT values_json FROM jy_records WHERE table_id=2').fetchall():
            values=report['values_json'];key=production_key(values)
            if key in totals:totals[key]+=decimal(values[5],True)
        output=[]
        for work in works:
            values=work['values_json'].copy();quantity=text(totals[production_key(values,True)])
            if str(values[9])==quantity:continue
            before=values[9];values[9]=quantity;meta={**work['meta'],**work_state(values,work['meta'].get('workStatus'))}
            con.execute('UPDATE jy_records SET values_json=%s,meta=%s,version=version+1,updated_at=now() WHERE id=%s',(Jsonb(values),Jsonb(meta),work['id']))
            audit(con,user,'work.production_total.reconcile',1,str(work['id']),before={'produced':before},after={'produced':quantity,'documentNo':values[14],'orderLineId':values[12]})
            if in_scope(user,work,scopes(con,user,1,'view')):output.append(public_record(con.execute('SELECT * FROM jy_records WHERE id=%s',(work['id'],)).fetchone()))
    return output
