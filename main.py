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

from jobs import redis_write, redis_read, redis_delete
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
        "progress": 0,
        "status": "checking"
    })
    
    return JSONResponse(content={"success": True, "task_id": task_id})


@app.get("/progress/{task_id}")
def check_progress(task_id: str):
    job = redis_read(task_id)

    if job is None:
        return {
            "progress": -1,
            "status": "error",
            "description": f"{task_id} is not valid or throws error in super_resolution.py"
        }

    return {
        "progress": job["progress"],
        "status": job["status"],
        "description": None
    }

    # if progress >= 100:
    #     # results 폴더에 결과 파일이 있는지에 따른 status 업데이트
    #     for file in os.listdir(RESULT_DIR):
    #         filename = os.path.basename(os.path.abspath(file))
    #         if filename.startswith(f"{task_id}_"):
    #             job["status"] = status = "done"
    #             break
    #     else:
    #         job["status"] = status = "finishing"
    #     redis_write(task_id, job)

@app.get("/results/{filename}")
def get_result(filename: str):
    file_path = os.path.join(RESULT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)