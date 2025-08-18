import os
import uuid
import logging
from datetime import datetime
from threading import Lock, Timer
from time import time
import boto3
from dotenv import load_dotenv
import io
import shutil

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from jobs import redis_write, redis_read
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


s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv('NAVER_OBJECT_STORAGE_ENDPOINT'),
    region_name=os.getenv('NAVER_OBJECT_STORAGE_REGION'),
    aws_access_key_id=os.getenv('NAVER_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('NAVER_SECRET_KEY'),
)

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    try:
        filename = file.name
        tmp_dir = os.path.join(BASE_DIR, "tmp")
        input_path = os.path.join(tmp_dir, "inputs", filename)

        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        s3_client.upload_file(input_path, "img-scaleup", f"inputs/{filename}")

    except Exception as e:
        logging.exception("file upload is failed")
        return JSONResponse(status_code=500, content={"success": False, "filename": filename})
    
    sr_task.apply_async(args=[filename, input_path, tmp_dir, 4, 512, 64, False])
    
    redis_write(filename, {
        "progress": 0,
        "status": "checking"
    })
    
    return JSONResponse(content={"success": True, "filename": filename})

@app.get("/progress/{filename}")
async def check_progress(filename: str):
    job = redis_read(filename)

    if job is None:
        return {
            "progress": -1,
            "status": "error",
            "description": f"{filename} is not valid or throws error in super_resolution.py"
        }

    return {
        "progress": job["progress"],
        "status": job["status"],
        "description": None
    }