"""Financial values are redacted from every JSON record response after authorization."""
from .db import CATALOG, scopes, is_admin


def financial_columns(table):
    return [i for i,name in enumerate(CATALOG.get(str(table),{}).get('fields',[])) if name in ['单价','金额']]


def denied_financial_columns(con,user):
    if is_admin(con,user):return {}
    return {int(table):columns for table in CATALOG if (columns:=financial_columns(table)) and not scopes(con,user,int(table),'financial_view')}


def redact_records(payload,denied):
    if isinstance(payload,list):
        for value in payload:redact_records(value,denied)
    elif isinstance(payload,dict):
        table=payload.get('table');columns=denied.get(table) if type(table) is int else None
        if columns and isinstance(payload.get('values'),list):
            for i in columns:
                if i<len(payload['values']):payload['values'][i]=''
        for value in payload.values():
            if isinstance(value,(dict,list)):redact_records(value,denied)
    return payload
