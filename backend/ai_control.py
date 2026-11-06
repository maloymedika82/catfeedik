"""Persisted provider cooldown, shared across videos and worker restarts. No raw keys are stored."""
import hashlib
import os
import time
from sqlalchemy import select,text
from .db import ProviderGate,AIRetry,RuntimeControl


def enabled(db):
    control=db.get(RuntimeControl,'ai_enabled')
    return control.value=='1' if control else os.getenv('AI_MODERATION_ENABLED','1')=='1'


def scope_key():
    key=os.getenv('AI_API_KEY')
    if not key:return None
    return hashlib.sha256(((os.getenv('AI_BASE_URL') or 'https://anymodel.org/v1').rstrip('/')+'\0'+key).encode()).hexdigest()


def gate_lock(db,scope):
    if db.bind.dialect.name=='postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':int(scope[:15],16)})


def next_provider_time(db):
    scope=scope_key()
    gate=db.get(ProviderGate,scope) if scope else None
    return gate.next_request_at if gate else 0


def reserve_request(factory):
    scope=scope_key()
    if not scope:return 0
    now=int(time.time())
    with factory() as db:
        gate_lock(db,scope)
        gate=db.scalar(select(ProviderGate).where(ProviderGate.scope==scope).with_for_update())
        if not gate:gate=ProviderGate(scope=scope,next_request_at=0);db.add(gate)
        if gate.next_request_at>now:return gate.next_request_at
        try:interval=max(1,int(os.getenv('AI_REQUEST_INTERVAL_SECONDS') or 1))
        except ValueError:interval=1
        gate.next_request_at=now+interval
        db.commit()
    return 0


def schedule_failure(db,feeding_id,error,attempt):
    details=getattr(error,'details',{}) or {}
    status=details.get('status',0)
    wait=max(60 if status==429 else 30,min(900,30*2**min(max(attempt-1,0),5)))
    wait=max(wait,details.get('retry_after_seconds',0))
    until=int(time.time())+wait
    retry=db.get(AIRetry,feeding_id)
    if not retry:retry=AIRetry(feeding_id=feeding_id);db.add(retry)
    retry.not_before=until;retry.category=details.get('category','technical_error');retry.http_status=status
    scope=scope_key()
    if scope and status in (429,503):
        gate_lock(db,scope)
        gate=db.scalar(select(ProviderGate).where(ProviderGate.scope==scope).with_for_update())
        if not gate:gate=ProviderGate(scope=scope,next_request_at=0);db.add(gate)
        gate.next_request_at=max(gate.next_request_at,until)
    return until


def defer_until(db,feeding_id,until):
    retry=db.get(AIRetry,feeding_id)
    if not retry:retry=AIRetry(feeding_id=feeding_id);db.add(retry)
    retry.not_before=until;retry.category='shared_provider_cooldown'
