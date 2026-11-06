"""List provider model IDs, never print tokens or raw HTTP error bodies."""
from pathlib import Path
import os
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.settings import load_environment
load_environment()
from backend.ai import base_url
import httpx
if not os.getenv('AI_API_KEY'):
    raise SystemExit('Set a new AI_API_KEY securely in .env first. Never paste it into chat.')
try:
    response=httpx.get(base_url()+'/models',headers={'Authorization':'Bearer '+os.environ['AI_API_KEY']},timeout=30,follow_redirects=False)
    response.raise_for_status()
    for model in response.json().get('data',[]):
        name=model.get('id','')
        if isinstance(name,str) and 'gemini' in name.lower():print(name)
except Exception:
    raise SystemExit('Could not read models. Check provider access, key and AI_BASE_URL; no credential values were logged.') from None
