"""Transactional points for approved feeding videos."""
from fastapi import HTTPException
from sqlalchemy import select
from .db import Feeding, Points, VideoAsset


def award(db, user, feeding):
    """Caller holds user and feeding locks; AI itself never writes points alone."""
    asset = db.get(VideoAsset, feeding.id)
    if not asset or asset.status != 'READY':
        raise HTTPException(409, 'Сначала видео должно пройти техническую обработку')
    previous = db.scalars(select(Feeding).where(Feeding.user_id == user.id, Feeding.status == 'APPROVED')).all()
    db.add(Points(user_id=user.id, event_key=f'feeding:{feeding.id}', delta=10, reason='Подтверждённое кормление'))
    if len(previous) == 4:
        db.add(Points(user_id=user.id, event_key=f'five:{user.id}', delta=5, reason='Бонус за пять кормлений'))
