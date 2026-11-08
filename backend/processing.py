import json
import os
import tempfile
import time
import uuid
from sqlalchemy import select,update,and_,or_,text
from fastapi import HTTPException
from .db import SessionLocal,User,Feeding,VideoAsset,AICheck,AIRetry
from .local_storage import storage_root,object_path,publish_file,sha256_file
from .video_processing import normalize,sample_frames,InvalidVideo
from .geography import nearest_city,city_info
from .fingerprint import video_fingerprint,has_similar
from .ai import moderate,ProviderUnavailable,configured
from .awards import award
from .ai_control import enabled,reserve_request,schedule_failure,defer_until


def process_video(feeding_id,session_factory=None):
    factory=session_factory or SessionLocal
    lease=uuid.uuid4().hex
    now=int(time.time())
    with factory() as db:
        claimed=db.execute(update(VideoAsset).where(VideoAsset.feeding_id==feeding_id,VideoAsset.attempts<3,
            or_(VideoAsset.status=='PENDING',and_(VideoAsset.status=='ERROR',VideoAsset.updated_at<=now-30),
                and_(VideoAsset.status=='PROCESSING',VideoAsset.updated_at<=now-600))).values(
                status='PROCESSING',lease=lease,attempts=VideoAsset.attempts+1,updated_at=now))
        if not claimed.rowcount:
            return {'status':'unchanged'}
        feeding=db.get(Feeding,feeding_id)
        key=feeding.object_key
        user_id=feeding.user_id
        city=city_info(feeding.city_id) or nearest_city(feeding.latitude,feeding.longitude)
        db.commit()
    published=[]
    try:
        source=object_path(key)
        digest=sha256_file(source)
        with tempfile.TemporaryDirectory(dir=storage_root()/'_incoming',prefix='process-') as directory:
            video,poster,duration=normalize(source,directory)
            try:
                fingerprint=video_fingerprint(video)
            except (OSError,ValueError):
                fingerprint=[]
            with factory() as db:
                duplicate=bool(db.scalar(select(VideoAsset.feeding_id).where(VideoAsset.source_hash==digest,VideoAsset.status=='READY',VideoAsset.feeding_id!=feeding_id).limit(1)))
                similar=has_similar(db,VideoAsset,fingerprint,feeding_id) if fingerprint else False
            verdict=None;ai_status='NOT_CONFIGURED';ai_reason='AI не настроен: требуется ручная проверка'
            ai_error=None;deferred=0;attempted=False
            with factory() as db:automatic=enabled(db)
            if duplicate:
                ai_status='SKIPPED_DUPLICATE';ai_reason='Обнаружено совпадение файла: требуется ручная проверка'
            elif not automatic:
                ai_status='PAUSED';ai_reason='Автоматическая AI-проверка выключена; требуется ручная проверка'
            else:
                try:
                    if configured():
                        deferred=reserve_request(factory)
                        if deferred:
                            ai_status='ERROR';ai_reason='AI ограничил запросы; видео доступно для ручной проверки'
                        else:
                            attempted=True;verdict=moderate(sample_frames(video,directory))
                    if verdict:
                        ai_status='DONE';ai_reason=verdict.reason
                except ProviderUnavailable as error:
                    ai_error=error;ai_status='ERROR';ai_reason='AI недоступен: видео передано на ручную проверку'
            output_key=f'processed/{feeding_id}/{lease}.mp4'
            poster_key=f'processed/{feeding_id}/{lease}.jpg'
            for file,destination in ((video,output_key),(poster,poster_key)):
                publish_file(file,destination,sha256_file(file));published.append(destination)
            with factory() as db:
                user=db.scalar(select(User).where(User.id==user_id).with_for_update())
                feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id).with_for_update())
                asset=db.scalar(select(VideoAsset).where(VideoAsset.feeding_id==feeding_id).with_for_update())
                if asset.lease!=lease:
                    for key in published:object_path(key).unlink(missing_ok=True)
                    return {'status':'lease_lost'}
                if db.bind.dialect.name=='postgresql':
                    db.execute(text('SELECT pg_advisory_xact_lock(:lock)'),{'lock':int(digest[:15],16)})
                    db.execute(text('SELECT pg_advisory_xact_lock(714292)'))
                duplicate=duplicate or bool(db.scalar(select(VideoAsset.feeding_id).where(VideoAsset.source_hash==digest,VideoAsset.status=='READY',VideoAsset.feeding_id!=feeding_id).limit(1)))
                similar=similar or (has_similar(db,VideoAsset,fingerprint,feeding_id) if fingerprint else False)
                flags=(["DUPLICATE_UPLOAD"] if duplicate else [])+(["SIMILAR_VIDEO"] if similar else [])+(["FINGERPRINT_UNAVAILABLE"] if not fingerprint else [])
                asset.status='READY';asset.source_hash=digest;asset.output_key=output_key;asset.poster_key=poster_key
                asset.duration=duration;asset.city_id=city['id'];asset.updated_at=int(time.time());asset.reason=''
                asset.flags=json.dumps(flags);asset.fingerprint=json.dumps(fingerprint)
                check=db.get(AICheck,feeding_id)
                if not check:check=AICheck(feeding_id=feeding_id);db.add(check)
                check.status=ai_status;check.model=verdict.provider_model if verdict else (os.getenv('AI_MODEL') or 'auto');check.reason=ai_reason
                check.decision=verdict.decision if verdict else 'REVIEW';check.confidence=verdict.confidence if verdict else 0
                check.attempts=(check.attempts or 0)+(1 if attempted else 0)
                if ai_error:schedule_failure(db,feeding_id,ai_error,check.attempts)
                elif deferred:defer_until(db,feeding_id,deferred)
                check.updated_at=int(time.time())
                db.flush()
                # Human claims and frozen/final accounts take priority over AI results.
                if feeding.status=='PROCESSING' and not user.frozen:
                    feeding.city=city['label'];feeding.status='REVIEW';feeding.decision_reason='Похоже на ранее отправленное видео: нужна ручная проверка' if similar else ai_reason
                    if verdict and not flags and enabled(db) and verdict.decision=='APPROVE':
                        try:
                            award(db,user,feeding)
                            feeding.status='APPROVED';feeding.decision_reason='Подтверждено AI и серверными проверками'
                        except HTTPException:
                            feeding.decision_reason='AI рекомендует одобрить; требуется проверка ограничений начисления'
                    elif verdict and not flags and enabled(db) and verdict.decision=='REJECT':
                        feeding.status='REJECTED';feeding.decision_reason=verdict.reason
                db.commit()
                return {'status':'READY','feeding_status':feeding.status}
    except Exception as exc:
        # Logs/DB never receive raw ffmpeg/provider output or secrets.
        invalid=isinstance(exc,InvalidVideo)
        with factory() as db:
            asset=db.get(VideoAsset,feeding_id)
            if asset and asset.lease==lease:
                asset.status='INVALID' if invalid else 'ERROR'
                asset.reason=str(exc) if invalid else 'Техническая ошибка обработки. Требуется повторная попытка.'
                asset.updated_at=int(time.time())
                feeding=db.get(Feeding,feeding_id)
                if feeding.status=='PROCESSING' and (invalid or asset.attempts>=3):
                    feeding.status='REVIEW';feeding.decision_reason=asset.reason
                db.commit()
        # Only these unique outputs belong to this failed attempt.
        for key in published:object_path(key).unlink(missing_ok=True)
        return {'status':'INVALID' if invalid else 'ERROR'}


def retry_ai(feeding_id,session_factory=None):
    """Retry only failed/missing AI; reuse the already verified MP4, never re-encode it."""
    if not configured():return {'status':'not_configured'}
    factory=session_factory or SessionLocal
    now=int(time.time())
    with factory() as db:
        if not enabled(db):return {'status':'paused'}
        existing=db.get(AICheck,feeding_id);feeding=db.get(Feeding,feeding_id)
        if not existing or existing.status not in ('ERROR','NOT_CONFIGURED','PAUSED') or existing.attempts>=3 or not feeding or feeding.status!='REVIEW' or feeding.claimed_by:
            return {'status':'unchanged'}
        scheduled=db.get(AIRetry,feeding_id)
        if scheduled and scheduled.not_before>now:return {'status':'deferred','retry_at':scheduled.not_before}
    delayed=reserve_request(factory)
    if delayed:return {'status':'deferred','retry_at':delayed}
    with factory() as db:
        check=db.scalar(select(AICheck).where(AICheck.feeding_id==feeding_id).with_for_update())
        feeding=db.get(Feeding,feeding_id);asset=db.get(VideoAsset,feeding_id)
        if not check or check.status not in ('ERROR','NOT_CONFIGURED','PAUSED') or check.attempts>=3:
            return {'status':'unchanged'}
        if not feeding or feeding.status!='REVIEW' or feeding.claimed_by or not asset or asset.status!='READY':
            return {'status':'unchanged'}
        user_id=feeding.user_id;key=asset.output_key
        check.status='RUNNING';check.attempts+=1;check.updated_at=now
        db.commit()
    verdict=None;ai_error=None
    try:
        with tempfile.TemporaryDirectory(dir=storage_root()/'_incoming',prefix='ai-') as directory:
            verdict=moderate(sample_frames(object_path(key),directory))
    except Exception as error:
        # Provider and media errors remain retryable, not a rejection.
        ai_error=error
    with factory() as db:
        user=db.scalar(select(User).where(User.id==user_id).with_for_update())
        feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id).with_for_update())
        check=db.scalar(select(AICheck).where(AICheck.feeding_id==feeding_id).with_for_update())
        asset=db.get(VideoAsset,feeding_id)
        if check.status!='RUNNING' or check.updated_at!=now:return {'status':'unchanged'}
        check.status='DONE' if verdict else 'ERROR';check.updated_at=int(time.time())
        if verdict:
            check.decision=verdict.decision;check.confidence=verdict.confidence;check.reason=verdict.reason;check.model=verdict.provider_model
            if feeding.status=='REVIEW' and not feeding.claimed_by and not user.frozen and not json.loads(asset.flags) and enabled(db):
                if verdict.decision=='APPROVE':
                    try:
                        award(db,user,feeding);feeding.status='APPROVED';feeding.decision_reason='Подтверждено AI и серверными проверками'
                    except HTTPException:
                        pass
                elif verdict.decision=='REJECT':
                    feeding.status='REJECTED';feeding.decision_reason=verdict.reason
        else:
            check.reason='AI недоступен; требуется ручная проверка'
            schedule_failure(db,feeding_id,ai_error,check.attempts)
        db.commit()
        return {'status':check.status,'feeding_status':feeding.status}
