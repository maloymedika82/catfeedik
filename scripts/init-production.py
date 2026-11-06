"""Create a private server template once, without copying or printing local secrets."""
import os
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[1]
target=root/'.env.production'
content=f'''# Fill on the server only. Never send this file to chat or GitHub.
APP_DOMAIN=
POSTGRES_PASSWORD={secrets.token_hex(32)}
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=animalfeedikbot
OWNER_TELEGRAM_IDS=2022054034
# Explicitly confirm deployment limits before starting:
MAX_VIDEO_BYTES=
LOCATION_RADIUS_METERS=
MAX_GPS_ACCURACY_METERS=
VIDEO_MIN_FREE_BYTES=536870912
AI_BASE_URL=https://anymodel.org/v1
AI_API_KEY=
AI_MODEL=auto
# Start with manual moderation while the provider is unavailable.
AI_MODERATION_ENABLED=0
AI_REQUEST_INTERVAL_SECONDS=1
'''
try:
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
except FileExistsError:
    raise SystemExit('.env.production already exists; no changes made.')
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    stream.write(content)
print('Created private .env.production. Fill domain, bot token and approved limits on the server. No credentials printed.')
