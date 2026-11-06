"""Run Celery worker + durable-job dispatcher. Solo pool also works on Windows."""
import os
from pathlib import Path
import subprocess
import sys
import time
import signal
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from backend.settings import load_environment
load_environment()
processes=[]
def stop(*_):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,stop)
try:
    for arguments in (
        ['worker','--pool=solo','--concurrency=1','--loglevel=INFO'],
        ['beat','--loglevel=INFO','--schedule',str(root/'.local'/'celerybeat-schedule')],
    ):
        processes.append(subprocess.Popen([sys.executable,'-m','celery','-A','backend.tasks.celery_app',*arguments],cwd=root))
    while True:
        if any(p.poll() is not None for p in processes):raise SystemExit('A worker process stopped; inspect its log.')
        time.sleep(.5)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:process.terminate()
    for process in processes:
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
