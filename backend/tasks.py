import os
import time
from celery import Celery
from sqlalchemy import select,or_,and_,update
from .db import SessionLocal,VideoAsset,AICheck,Feeding
from .processing import process_video,retry_ai
from .ai import configured

celery_app=Celery('catfeedik',broker=os.getenv('REDIS_URL') or 'redis://127.0.0.1:6379/0')
celery_app.conf.update(task_serializer='json',accept_content=['json'],result_serializer='json',
    task_ignore_result=True,broker_connection_retry_on_startup=True,
    task_default_queue=os.getenv('CELERY_QUEUE') or 'catfeedik',
    task_acks_late=True,worker_prefetch_multiplier=1,broker_transport_options={'visibility_timeout':900,'global_keyprefix':(os.getenv('CELERY_QUEUE') or 'catfeedik')+':'},
    beat_schedule={'recover-video-jobs':{'task':'catfeedik.dispatch','schedule':15.0}})

@celery_app.task(name='catfeedik.process',soft_time_limit=240,time_limit=300)
def process(feeding_id):
    return process_video(feeding_id)

@celery_app.task(name='catfeedik.dispatch')
def dispatch():
    now=int(time.time())
    with SessionLocal() as db:
        ids=list(db.scalars(select(VideoAsset.feeding_id).where(VideoAsset.attempts<3,
            or_(VideoAsset.status=='PENDING',and_(VideoAsset.status=='ERROR',VideoAsset.updated_at<=now-30),
                and_(VideoAsset.status=='PROCESSING',VideoAsset.updated_at<=now-600))).limit(100)))
    for item in ids:process.delay(item)
    if configured():
        with SessionLocal() as db:
            db.execute(update(AICheck).where(AICheck.status=='RUNNING',AICheck.updated_at<now-300).values(status='ERROR'))
            db.commit()
            pending=list(db.scalars(select(AICheck.feeding_id).join(Feeding,Feeding.id==AICheck.feeding_id)
                .where(AICheck.status.in_(['ERROR','NOT_CONFIGURED']),AICheck.attempts<3,AICheck.updated_at<=now-30,
                    Feeding.status=='REVIEW',Feeding.claimed_by.is_(None)).limit(100)))
        for item in pending:analyze.delay(item)
    return len(ids)


@celery_app.task(name='catfeedik.analyze',soft_time_limit=120,time_limit=180)
def analyze(feeding_id):
    return retry_ai(feeding_id)
