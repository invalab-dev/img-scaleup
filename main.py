import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from threading import Lock, Timer
from time import time
from dotenv import load_dotenv
import shutil
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from jobs import redis_write, redis_read, redis_delete
from tasks import sr_task

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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


@app.post("/start")
async def start(id: str):
    tmp_dir = os.path.join(BASE_DIR, "tmp")
    for file in Path(os.path.join(tmp_dir, "inputs")).iterdir():
        if file.is_file() and file.stem == id:
            filename = file.name
            break
    if not filename:
        return JSONResponse(status_code=500, content=f"{id} related file not found")

    input_path = os.path.join(tmp_dir, "inputs", filename)
        
    redis_write(id, {
        "progress": 0,
        "started_time": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "completed_time": None,
        "output_path": None
    })

    sr_task.apply_async(args=[id, input_path, tmp_dir, 4, 512, 64, False], queue='gpu')
    
    return JSONResponse(content="")

@app.post("/save-file")
async def save_file(id: str, filename: str, request: Request):
    try:
        tmp_dir = os.path.join(BASE_DIR, "tmp")
        input_path = os.path.join(tmp_dir, "inputs", filename)

        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        
    except Exception as e:
        return JSONResponse(status_code=500, content=f"Failed to save file: {filename}")

@app.get("/progress")
async def progress(id: str):
    job = redis_read(id)

    if job is None:
        logging.exception(f"{id} is not valid or throws error in super_resolution.py")

    return JSONResponse(
        status_code=500, 
        content={
            "progress": job["progress"],
            "completed_time": job["completed_time"],
        }
    )
    
@app.get("/download")
async def download(id: str):
    job = redis_read(id)

    def iter_file():
        with open(job["output_path"], mode="rb") as f:
            while chunk := f.read(1024 * 1024):
                yield chunk

    return StreamingResponse(iter_file(), media_type="application/octet-stream")

@app.get("/delete")
async def delete(id: str):
    job = redis_read(id)
    os.remove(job["output_path"])
    redis_delete(id, ex=0)
