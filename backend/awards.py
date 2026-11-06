import math
import os
from fastapi import HTTPException
from sqlalchemy import select
from .db import Feeding,Points,VideoAsset
from .settings import product_number


def distance(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(a.latitude,a.longitude,b.latitude,b.longitude))
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))


def award(db,user,feeding):
    """Caller holds user and feeding locks; AI itself never writes the ledger."""
    asset=db.get(VideoAsset,feeding.id)
    if not asset or asset.status!='READY':
        raise HTTPException(409,'Сначала видео должно пройти техническую обработку')
    try:
        radius=product_number('LOCATION_RADIUS_METERS',100)
        accuracy=product_number('MAX_GPS_ACCURACY_METERS',50)
    except ValueError:
        raise HTTPException(503,'Проверьте настройки локации') from None
    if not radius or not accuracy:
        raise HTTPException(503,'Радиус локации и точность GPS ещё не утверждены')
    if feeding.accuracy>accuracy:
        raise HTTPException(422,'Точность геолокации недостаточна')
    previous=db.scalars(select(Feeding).where(Feeding.user_id==user.id,Feeding.status=='APPROVED')).all()
    if any(abs(feeding.created_at-old.created_at)<7*86400 and distance(feeding,old)<=radius for old in previous):
        raise HTTPException(409,'Повторный зачёт в этой локации доступен через 7 дней')
    db.add(Points(user_id=user.id,event_key=f'feeding:{feeding.id}',delta=10,reason='Подтверждённое кормление'))
    if len(previous)==4:
        db.add(Points(user_id=user.id,event_key=f'five:{user.id}',delta=5,reason='Бонус за пять кормлений'))
