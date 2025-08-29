from celery import Celery
import boto3
import os
from datetime import datetime 
from zoneinfo import ZoneInfo
from jobs import redis_delete, redis_read, redis_write 

broker = 'redis://localhost:6379/0'          # 또는 'redis://:PASSWORD@localhost:6379/0'
backend = 'redis://localhost:6379/1'

celery = Celery('sr_tasks', broker=broker, backend=backend)
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='Asia/Seoul',
    enable_utc=True,
)


@celery.task(bind=True)
def sr_task(self, id, scale=4, tile_size=512, tile_pad=64, use_memmap=False):
    # lazy import to avoid loading heavy libs at Celery master import time if desired
    from super_resolution import run_super_resolution

    output_path = run_super_resolution(id, scale=scale, tile_size=tile_size, tile_pad=tile_pad, use_memmap=use_memmap)

    job = redis_read(id)
    job["progress"] = 100
    job["completed_time"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    job["output_path"] = output_path
    redis_write(id, job)
