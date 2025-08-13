from celery import Celery

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
def sr_task(self, upload_path, output_dir, scale=4, tile_size=512, tile_pad=64, use_memmap=False, task_id=None):
    # lazy import to avoid loading heavy libs at Celery master import time if desired
    from super_resolution import run_super_resolution
    result_path = run_super_resolution(upload_path, output_dir, scale=scale, tile_size=tile_size, tile_pad=tile_pad, use_memmap=use_memmap, task_id=task_id)
    return result_path