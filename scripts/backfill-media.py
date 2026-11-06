"""Queue legacy local originals for validation without changing decisions or awarding points."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.settings import load_environment
load_environment()
from backend.db import Base,engine,SessionLocal,Feeding,VideoAsset
from backend.local_storage import object_path
from sqlalchemy import select
Base.metadata.create_all(engine)
count=0
with SessionLocal() as db:
    for feeding in db.scalars(select(Feeding).outerjoin(VideoAsset,VideoAsset.feeding_id==Feeding.id).where(VideoAsset.feeding_id.is_(None),Feeding.status.in_(['REVIEW','APPROVED']))):
        if object_path(feeding.object_key).is_file():
            db.add(VideoAsset(feeding_id=feeding.id));count+=1
    db.commit()
print(f'Queued {count} legacy local originals. Existing decisions and points preserved.')
