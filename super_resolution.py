import os
import cv2
import numpy as np
import torch
import io
import contextlib
import time
from PIL import Image
from tqdm import tqdm
import math
import rasterio
from rasterio.transform import Affine

from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet

from jobs import redis_read, redis_write, redis_delete


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "weights", "RealESRGAN_x4plus.pth")

def load_image(path, max_retries=10, delay=0.5):
    for attempt in range(max_retries):
        if os.path.exists(path):
            try:
                img = Image.open(path).convert('RGB')
                arr = np.array(img, dtype=np.uint8)
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            except Exception:
                pass
        time.sleep(delay)
    raise FileNotFoundError(f"파일을 열 수 없습니다: {path}")

def save_final_image(arr, dst_path):
    img = Image.fromarray(arr, 'RGB')
    os.makedirs(os.path.dirname(dst_path) or '.', exist_ok=True)
    img.save(dst_path)

def save_final_image_with_metadata(input_tif, result_array, output_tif):
    with rasterio.open(input_tif) as src:
        original_crs = src.crs
        original_transform = src.transform
        original_driver = src.driver

        scale_x = result_array.shape[1] / src.width
        scale_y = result_array.shape[0] / src.height

        new_transform = Affine(
            original_transform.a / scale_x, original_transform.b, original_transform.c,
            original_transform.d, original_transform.e / scale_y, original_transform.f
        )

        profile = {
            'driver': original_driver,
            'height': result_array.shape[0],
            'width': result_array.shape[1],
            'count': 3,
            'dtype': 'uint8',
            'crs': original_crs,
            'transform': new_transform
        }

        with rasterio.open(output_tif, 'w', **profile) as dst:
            for i in range(3):
                dst.write(result_array[:, :, i], i + 1)

def run_super_resolution(
    filename,
    input_path,
    tmp_dir,
    scale=4,
    tile_size=512,
    tile_pad=64,
    use_memmap=False):
    try:
        def update_progress(p):
            p = max(0, min(100, int(p)))
            job = redis_read(filename)
            job["progress"] = p
            print(f"update_progress: {filename} / {p}")
            redis_write(filename, job)

        update_progress(0)

        img_bgr = load_image(input_path)
        H, W = img_bgr.shape[:2]
        H2, W2 = int(H * scale), int(W * scale)

        net = RRDBNet(num_in_ch=3, num_out_ch=3,
                      num_feat=64, num_block=23,
                      num_grow_ch=32, scale=scale)
        model = RealESRGANer(
            scale=scale,
            model_path=MODEL_PATH,
            dni_weight=None,
            model=net,
            tile=0,
            tile_pad=tile_pad,
            pre_pad=0,
            half=False,
            device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        )

        if use_memmap:
            memmap_path = os.path.join(tmp_dir, 'temp_memmap.dat')
            if os.path.exists(memmap_path):
                os.remove(memmap_path)
            out = np.memmap(memmap_path, dtype='uint8', mode='w+', shape=(H2, W2, 3))
        else:
            out = np.zeros((H2, W2, 3), dtype='uint8')

        step = tile_size - tile_pad
        windows = [
            (x, y,
             min(tile_size, W - x),
             min(tile_size, H - y))
            for y in range(0, H, step)
            for x in range(0, W, step)
        ]
        total_tiles = len(windows)
        completed = 0

        update_progress(5)

        with tqdm(total=total_tiles, desc='SR 진행', dynamic_ncols=True) as pbar:
            for idx, (x, y, w, h) in enumerate(windows):
                tile_bgr = img_bgr[y:y + h, x:x + w]
                buf = io.StringIO()
                with torch.no_grad(), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    sr_bgr, _ = model.enhance(tile_bgr, outscale=scale)
                sr_rgb = cv2.cvtColor(sr_bgr, cv2.COLOR_BGR2RGB)
                y2, x2 = y * scale, x * scale
                out[y2:y2 + sr_rgb.shape[0], x2:x2 + sr_rgb.shape[1], :] = sr_rgb
                if use_memmap:
                    out.flush()

                completed += 1
                log_msg = f"[{completed}/{total_tiles}] 타일 처리 완료"
                tqdm.write(log_msg)
                update_progress(min(99, math.ceil((completed / total_tiles) * 100)))
                pbar.update(1)

        output_path = os.path.join(BASE_DIR, "outputs", filename)

        if filename.lower().endswith(".tif") or filename.lower().endswith(".tiff"):
            save_final_image_with_metadata(input_path, out, output_path)
        else:
            save_final_image(out, output_path)

        if use_memmap and os.path.exists(memmap_path):
            os.remove(memmap_path)

        job = redis_read(filename)
        job["output"] = output_path
        redis_write(filename, job)

        update_progress(100)

    except Exception as e:
        if filename:
            redis_delete(filename, ex=0)  # 즉시 삭제해도 괜찮은가?
        raise RuntimeError(f"[SR 오류] {str(e)}")

# GPU 워커에서 사용하는 함수명 그대로 유지
run_super_resolution_gpu = run_super_resolution