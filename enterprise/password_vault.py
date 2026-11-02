"""Recoverable passwords are encrypted separately from authentication hashes."""
import json
import os
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet,InvalidToken


def vault():
    configured=os.environ.get('JY_PASSWORD_VAULT_KEY')
    if configured:return Fernet(configured.encode())
    path=Path(os.environ.get('JY_PASSWORD_VAULT_FILE',str(Path.home()/'.local/share/jiayang/password-vault.key')))
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not path.exists():
        descriptor,temporary=tempfile.mkstemp(prefix='.vault-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'wb') as file:file.write(Fernet.generate_key());file.flush();os.fsync(file.fileno())
            try:os.link(temporary,path)
            except FileExistsError:pass
        finally:os.unlink(temporary)
    return Fernet(path.read_bytes().strip())


def seal_password(username,password):
    return vault().encrypt(json.dumps({'username':username,'password':password},ensure_ascii=False).encode()).decode()


def read_password(username,cipher):
    if not cipher:return None
    try:
        data=json.loads(vault().decrypt(cipher.encode()))
        return data['password'] if data.get('username')==username and isinstance(data.get('password'),str) else None
    except (InvalidToken,ValueError,KeyError,TypeError):return None


def password_view_allowed(con,user):
    from .db import is_admin
    if not is_admin(con,user):return False
    rows=con.execute("SELECT values_json FROM jy_records WHERE table_id=14 AND values_json->>3=%s AND values_json->>6='用户与权限' AND values_json->>7='密码是否见'",(user['username'],)).fetchall()
    return bool(rows) and all(row['values_json'][8]=='允许' for row in rows)
