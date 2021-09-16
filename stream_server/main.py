import asyncio
import datetime
import os
import threading
import traceback
import uuid
import random
from typing import Optional

import pytz
from urllib import parse
from apscheduler.schedulers import SchedulerNotRunningError, SchedulerAlreadyRunningError
from jinja2 import Environment, FileSystemLoader
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Cookie, FastAPI, Request, Depends, HTTPException, File, UploadFile, Form
from pydantic import BaseModel
from starlette.responses import FileResponse

# 新数据库ORM
from sqlalchemy.orm import Session
from .util.config import file_path
from .util.audio import *
app = FastAPI()


def localize(utctime):
    tz = pytz.timezone('Asia/Shanghai')
    if utctime.tzinfo is None:
        utctime = utctime.replace(tzinfo=pytz.timezone('UTC'))
    if utctime.timestamp() == 0:
        return "Instantly"
    else:
        localtime = utctime.astimezone(tz)
    return localtime.strftime("%Y-%m-%d %H:%M:%S")


env = Environment(loader=FileSystemLoader('./html/templates'), autoescape=True)
template = Jinja2Templates('./html/templates')
template.env.filters['localize'] = localize
app.mount("/static", StaticFiles(directory="./html/templates"), name="static")
# app.mount("/audio", StaticFiles(directory="./audio"), name="static")

mute_process = MuteProcess()

login_rec = {}

class LoginAuth(BaseModel):
    username: str
    password: str
    is_guest: Optional[bool] = None


class CalendarEvent(BaseModel):
    title: str
    start: datetime.datetime
    end: datetime.datetime


@app.get("/")
def read_root():
    return {"msg": "Please redirect to https://shallrest.space:8000/home"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}


@app.get("/upload", response_class=HTMLResponse)
async def file_upload(request: Request):
    return template.TemplateResponse('file_upload_page.html', {
        "request": request
    })


@app.post("/upload", status_code=201)
async def file_upload_post(file: UploadFile = File(...)):
    if file.content_type.find("audio") == -1 and file.content_type.find("video") == -1:
        raise HTTPException(status_code=400, detail="Invalid filetype")
    content = await file.read()
    with open(os.path.join(file_path, file.filename), "wb") as f:
        f.write(content)
    return {"filename": file.filename, "status": "succeeded"}


@app.post("/system/start_stream")
async def start_stream():
    try:
        MuteProcess.set_mutefile("MuteSound.mp3")
        threading.Thread(target=MuteProcess.run).start()
    except:
        traceback.print_exc()


@app.post("/set_cookie")
async def set_cookie():
    content = {"message": "Come to the dark side, we have cookies"}
    response = JSONResponse(content=content)
    response.set_cookie(key="fakesession", value="fake-cookie-session-value")
    return response


@app.get("/remote/stop")
def system_stop_audio():
    AudioProcess.stop_all()


@app.post("/remote/play/{filename}")
def remote_play_command(filename:str):
    print("remote play command received:"+filename)
    audio = AudioProcess(os.path.join(file_path,filename))
    threading.Thread(target=audio.run).start()


@app.get("/remote/find/{filename}")
def remote_find_file(filename:str):
    file_list = os.listdir(file_path)
    try:
        file_list.index(filename)
    except ValueError:
        raise HTTPException(404)
    return


@app.post("/remote/upload", status_code=201)
async def file_upload_post(file: UploadFile = File(...)):
    try:
        content = await file.read()
        with open(os.path.join(file_path, file.filename), "wb") as f:
            f.write(content)
    except Exception:
        traceback.print_exc()
    return {"filename": file.filename, "status": "succeeded"}
