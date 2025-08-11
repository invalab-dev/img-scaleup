import os
import uuid
import logging
from datetime import datetime
from threading import Lock, Timer
from time import time

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from super_resolution import run_super_resolution
from jobs import jobs, safe_write, safe_read

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RESULT_DIR = os.path.join(BASE_DIR, "results")

app = FastAPI()

class SuppressProgressLogsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/progress/") or request.url.path.startswith("/update-progress"):
            logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        else:
            logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        return await call_next(request)

app.add_middleware(SuppressProgressLogsMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...)
):
    try:
        task_id = uuid.uuid4().hex
        filename = f"{task_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)

        with open(file_path, 'wb') as f:
            f.write(await file.read())

        safe_write(task_id, {
            "filename": filename,
            "file_path": file_path,
            "progress": 0,
            "status": "checking"
        })

        print(f"task_id: {task_id}")

        out_name = run_super_resolution(
                    input_path=file_path,
                    output_dir=RESULT_DIR,
                    scale=4,
                    tile_size=512,
                    tile_pad=64,
                    use_memmap=False,
                    task_id=task_id
        )

        return JSONResponse(content={"success": True, "task_id": task_id})
    
    except Exception as e:
        logging.exception("Upload failed")
        return JSONResponse(status_code=500, content={"success": False, "task_id": None})

@app.get("/progress/{task_id}")
def check_progress(task_id: str):
    job = safe_read(task_id)
    progress = job["progress"]
    status = job["status"]
    filename = job["filename"]

    if progress >= 100 and not filename:
        for f in os.listdir(RESULT_DIR):
            if f.startswith(f"SR_{task_id}_"):
                filename = f
                status = "done"
                # 5분(300초) 후 파일 다운로드 기능 제거 (jobs 메모리 점유 증가 제한)
                Timer(300, lambda: safe_write(task_id, None))
                break
        else:
            status = "finishing"

    return {
        "progress": progress,
        "filename": filename,
        "status": status
    }

@app.get("/results/{filename}")
def get_result(filename: str):
    file_path = os.path.join(RESULT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)