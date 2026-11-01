"""Remove one linked confirmation entry while preserving other order batches."""
import re
from decimal import Decimal, InvalidOperation
from psycopg.types.json import Jsonb
from .db import audit


def token(value):
    match = re.fullmatch(r'(贴合|泡棉)\+?(\d{4})/(\d{1,2})/(\d{1,2})(?:\+|[：:])\s*(\d+(?:\.\d+)?)', str(value or '').strip())
    if not match:
        return None
    kind, year, month, day, quantity = match.groups()
    return kind, f'{int(year)}/{int(month)}/{int(day)}', Decimal(quantity)


def remove_history_line(history, values, link=None):
    history = str(history or '')
    lines = history.split('\n')
    parsed = [token(line) for line in lines]
    if link and link.get('entry'):
        target = token(link['entry'])
        candidates = [i for i, item in enumerate(parsed) if item and item == target]
    else:
        try:
            quantity = Decimal(str(values[8]).replace(',', '').replace('，', '').strip())
        except InvalidOperation:
            return history
        kind = str(values[13]).strip()
        date = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', str(values[0]))
        day = '/'.join(str(int(v)) for v in date.groups()) if date else None
        candidates = [i for i, item in enumerate(parsed) if item and item[0] == kind and item[2] == quantity]
        exact = [i for i in candidates if parsed[i][1] == day]
        if exact:
            candidates = exact
        elif len({parsed[i][1] for i in candidates}) > 1:
            raise ValueError('历史打印记录无法唯一对应，请先核对工单日期和数量')
    if candidates:
        lines.pop(candidates[-1])
    return '\n'.join(lines)


def unlink_work_history(con, user, work):
    from .api import fail
    link = work['meta'].get('printHistory', {})
    source = str(link.get('sourceId', work['values_json'][12])).strip()
    if not source:
        return None
    sale = con.execute("SELECT * FROM jy_records WHERE table_id=0 AND btrim(values_json->>21)=%s", (source,)).fetchone()
    if not sale:
        return None
    try:
        history = remove_history_line(sale['values_json'][26], work['values_json'], link)
    except ValueError as error:
        fail(409, str(error))
    if history == str(sale['values_json'][26] or ''):
        return None
    values = sale['values_json'].copy()
    values[26] = history
    con.execute('UPDATE jy_records SET values_json=%s,version=version+1,updated_at=now() WHERE id=%s', (Jsonb(values), sale['id']))
    audit(con, user, 'sales.work_print_deleted', 0, str(sale['id']), before={'history':sale['values_json'][26]}, after={'history':history,'workId':str(work['id'])})
    return str(sale['id'])
