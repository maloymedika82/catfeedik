"""Start the local API, preserving injected settings. Never log credential values."""
import os
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
os.chdir(root)
for name in ('.env','.local/services.env'):
    path=root/name
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
                continue
            key,value=line.split('=',1)
            os.environ.setdefault(key.strip(),value.strip())
os.execv(sys.executable,[sys.executable,'-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','8000'])
