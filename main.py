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


@app.post("/upload")
async def upload(image: UploadFile = File(...)):
    try:
        filename = image.filename
        tmp_dir = os.path.join(BASE_DIR, "tmp")
        input_path = os.path.join(tmp_dir, "inputs", filename)

        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        
    except Exception as e:
        logging.exception("file upload is failed")
        return JSONResponse(status_code=500, content={"filename": filename})
    
    sr_task.apply_async(args=[filename, input_path, tmp_dir, 4, 512, 64, False], queue='gpu')
    
    redis_write(filename, {
        "progress": 0
    })
    
    return JSONResponse(content={"filename": filename})

@app.get("/progress/{filename}")
async def progress(filename: str):
    job = redis_read(filename)

    if job is None:
        logging.exception(f"{filename} is not valid or throws error in super_resolution.py")
        return JSONResponse(status_code=500, content=job)
    else:
        return JSONResponse(content=job)
    

@app.get("/download/{filename}")
async def download(filename: str):
    job = redis_read(filename)
    return FileResponse(job["output"])

@app.get("/delete/{filename}")
async def delete(filename: str):
    job = redis_read(filename)
    os.remove(job["output"])
    redis_delete(filename, ex=0)
