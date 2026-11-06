import os
from pathlib import Path


def load_environment():
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    for name in ('.env','.local/services.env'):
        path=root/name
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                    key,value=line.split('=',1)
                    os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))


def product_number(name,development_default):
    raw=os.getenv(name)
    if not raw and os.getenv('APP_ENV')=='development':
        return development_default
    if not raw:
        return None
    value=float(raw)
    if value<=0:
        raise ValueError(f'{name} must be positive')
    return value
