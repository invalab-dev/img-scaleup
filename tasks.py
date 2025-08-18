from celery import Celery
import boto3
import os
from jobs import redis_delete 

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

s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv('NAVER_OBJECT_STORAGE_ENDPOINT'),
    region_name=os.getenv('NAVER_OBJECT_STORAGE_REGION'),
    aws_access_key_id=os.getenv('NAVER_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('NAVER_SECRET_KEY'),
)

@celery.task(bind=True)
def sr_task(self, filename, input_path, tmp_dir, scale=4, tile_size=512, tile_pad=64, use_memmap=False):
    # lazy import to avoid loading heavy libs at Celery master import time if desired
    from super_resolution import run_super_resolution
    
    output_path = run_super_resolution(filename, input_path, tmp_dir, scale=scale, tile_size=tile_size, tile_pad=tile_pad, use_memmap=use_memmap)
    s3_client.upload_file(output_path, "img-scaleup", f"outputs/{filename}")

    if(os.path.exists(output_path)):
        os.remove(output_path)
    if(os.path.exists(input_path)):
        os.remove(input_path)
    redis_delete(filename, ex=0)
