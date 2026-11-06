"""Generate development-only database credentials, never replace existing files."""
from pathlib import Path
import secrets
import os
root=Path(__file__).resolve().parents[1]
local=root/'.local'
local.mkdir(exist_ok=True,mode=0o700)
config=local/'services.env'
if not config.exists():
    password=secrets.token_hex(24)
    fd=os.open(config,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(f'POSTGRES_PASSWORD={password}\nDATABASE_URL=postgresql+psycopg://catfeedik:{password}@127.0.0.1:5432/catfeedik\nAPP_ENV=development\nALLOW_DEV_LOGIN=1\n')
print('Local development configuration is present (.local/services.env).')
