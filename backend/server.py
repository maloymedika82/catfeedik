"""Fail closed before importing the production API if required settings are missing."""
import math
import os
import re
import sys


def validate(environment):
    problems=[]
    if environment.get('APP_ENV')!='production':problems.append('APP_ENV')
    for name in ('ALLOW_DEV_LOGIN','ALLOW_DEV_ADMIN'):
        if environment.get(name)!='0':problems.append(name)
    if not environment.get('DATABASE_URL','').startswith('postgresql+psycopg://'):problems.append('DATABASE_URL')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',environment.get('TELEGRAM_BOT_TOKEN','')):problems.append('TELEGRAM_BOT_TOKEN')
    for name in ('MAX_VIDEO_BYTES','LOCATION_RADIUS_METERS','MAX_GPS_ACCURACY_METERS'):
        try:
            value=float(environment.get(name,''))
            if not math.isfinite(value) or value<=0:raise ValueError()
            if name=='MAX_VIDEO_BYTES' and (not value.is_integer() or value>24_000_000):raise ValueError()
        except (ValueError,TypeError):problems.append(name)
    if problems:raise ValueError('Set valid production settings: '+', '.join(problems))


if __name__=='__main__':
    try:validate(os.environ)
    except ValueError as error:raise SystemExit(str(error)) from None
    os.execv(sys.executable,[sys.executable,'-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','8000','--no-proxy-headers'])
