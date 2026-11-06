"""Start the local API, preserving injected settings. Never log credential values."""
import os
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0,str(root))
from backend.settings import load_environment
load_environment()
os.execv(sys.executable,[sys.executable,'-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','8000'])
