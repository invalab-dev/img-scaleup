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

from jobs import redis_write, redis_read
from tasks import sr_task

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
        upload_path = os.path.join(UPLOAD_DIR, f"{task_id}_{file.filename}")

        with open(upload_path, 'wb') as f:
            f.write(await file.read())
    except Exception as e:
        logging.exception("upload failed")
        return JSONResponse(status_code=500, content={"success": False, "task_id": None})
    
    result = sr_task.apply_async(args=[upload_path, RESULT_DIR, 4, 512, 64, False, task_id], queue='gpu')
    
    redis_write(task_id, {
        "file_path": upload_path,
        "progress": 0,
        "status": "checking"
    })
    
    return JSONResponse(content={"success": True, "task_id": task_id})


@app.get("/progress/{task_id}")
def check_progress(task_id: str):
    job = redis_read(task_id)
    progress = job["progress"]
    status = job["status"]
    filename = job["filename"]

    if progress >= 100 and not filename:
        for f in os.listdir(RESULT_DIR):
            if f.startswith(f"SR_{task_id}_"):
                filename = f
                status = "done"
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