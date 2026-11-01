"""Derived remaining work quantity and one-way automatic closure."""
import re
from decimal import Decimal, InvalidOperation, localcontext


def work_state(values, prior=None):
    status = '关闭' if prior in ('关闭', '已关闭') else '审核'
    quantity = re.sub(r'[\s,，]', '', str(values[8] if values[8] is not None else ''))
    produced = re.sub(r'[\s,，]', '', str(values[9] if values[9] is not None else '')) or '0'
    owing = ''
    if quantity:
        try:
            with localcontext() as context:
                context.prec = max(80, len(quantity) + len(produced) + 64)
                planned, done = Decimal(quantity), Decimal(produced)
                if not planned.is_finite() or not done.is_finite() or abs(planned.as_tuple().exponent)>24 or abs(done.as_tuple().exponent)>24:
                    raise InvalidOperation()
                balance = planned - done
                if balance == 0:
                    owing, status = '0', '关闭'
                else:
                    owing = format(balance, 'f')
                    if '.' in owing:
                        owing = owing.rstrip('0').rstrip('.')
        except (InvalidOperation, ValueError):
            pass
    return {'workStatus': status, 'workOwing': owing}
