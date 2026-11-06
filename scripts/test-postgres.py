"""Run integration tests in isolated PostgreSQL schemas; never touch application tables."""
import os
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0,str(root))
if not os.getenv('TEST_DATABASE_URL'):
    path=root/'.local/services.env'
    if not path.exists():
        raise SystemExit('Run scripts/init-local.py and docker compose first.')
    settings=dict(line.split('=',1) for line in path.read_text().splitlines() if '=' in line)
    os.environ['TEST_DATABASE_URL']=settings['DATABASE_URL']
import pytest
raise SystemExit(pytest.main(['backend/tests','-q']))
