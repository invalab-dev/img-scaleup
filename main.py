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
TEMP_DIR = os.path.join(BASE_DIR, "tmp")

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
    redis_write(id, {
        "progress": 0, 
        "started_time": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "completed_time": None
    })

    sr_task.apply_async(args=[id, 4, 512, 64, False], queue='gpu')
    
    return JSONResponse(content="")

@app.post("/save-file")
async def save_file(id: str, filename: str, request: Request):
    try:
        dir = os.path.join(TEMP_DIR, id, "inputs")
        os.makedirs(dir, exist_ok=True)
        input_path = os.path.join(dir, filename)

        with open(input_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)

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
            "started_time": job["started_time"],
            "completed_time": job["completed_time"],
        }
    )
    
@app.get("/download")
async def download(id: str):
    job = redis_read(id)

    output_path = Path(os.path.join(TEMP_DIR, id, "outputs")).iterdir()[0]

    def iter_file():
        with open(output_path, mode="rb") as f:
            while chunk := f.read(1024 * 1024):
                yield chunk

    return StreamingResponse(iter_file(), media_type="application/octet-stream")

@app.get("/delete")
async def delete(id: str):
    shutil.rmtree(os.path.join(TEMP_DIR, id, "inputs"))
    shutil.rmtree(os.path.join(TEMP_DIR, id, "outputs"))
    redis_delete(id, ex=0)
