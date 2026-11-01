import argparse
import getpass
import os

import uvicorn

from .db import PASSWORDS, Store, audit, validate_password


def main():
    parser=argparse.ArgumentParser(description='Jiayang enterprise server')
    parser.add_argument('command', choices=['serve','bootstrap','reset-password'], nargs='?', default='serve')
    parser.add_argument('--username', default='admin')
    args=parser.parse_args()
    if args.command=='serve':
        uvicorn.run('enterprise.api:create_app',factory=True,host='0.0.0.0',port=int(os.environ.get('PORT','8765')),access_log=False)
        return
    store=Store(os.environ['DATABASE_URL']);store.initialize()
    password=getpass.getpass('New password (at least 10 characters): ')
    validate_password(password)
    if password!=getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords do not match')
    if args.command=='bootstrap':
        store.bootstrap(args.username,password)
    else:
        with store.connect(write=True) as con:
            user=con.execute('SELECT * FROM jy_users WHERE username=%s',(args.username,)).fetchone()
            if not user:raise SystemExit('User not found')
            con.execute('UPDATE jy_users SET password_hash=%s,must_change_password=true,version=version+1 WHERE id=%s',(PASSWORDS.hash(password),user['id']))
            con.execute('DELETE FROM jy_sessions WHERE user_id=%s',(user['id'],))
            audit(con,{'username':'server-console'},'user.console_password_reset',record_id=str(user['id']))
    print('Account updated. Password has not been logged.')


if __name__=='__main__':main()
