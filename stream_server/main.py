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

from .database import crud, models, schemas
from .database import engine, get_db
from .util.schedulerUtil import sche

from .util.config import file_path
from .util.audio import *

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

login_rec = {}


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
    return {"msg": "Please redirect to http://182.92.3.1:8000/home"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}


# 服务端创建用户（测试用功能）
@app.post("/users/", response_model=schemas.UserInfo)
def create_user(user: schemas.UserInfoCreate, db: Session = Depends(get_db)):
    db_user = crud.get_userinfo_by_name(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="username already exists")
    return crud.create_userinfo(db, userinfo=user)


# 显示登录页面
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return template.TemplateResponse('login_page.html', {
        "request": request
    })


# post登录信息
@app.post("/login/post")
async def login(auth: schemas.UserAuth, login_id: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    '''
    if auth.is_guest:
        response = JSONResponse(content={"status": "guest"})
        uid = str(uuid.uuid4())
        suid = ''.join(uid.split('-'))
        login_rec[suid] = auth.username
        response.set_cookie(key="login_id", value=suid)
        return response
    '''
    auth_res = crud.auth_user(db=db, username=auth.username, password_checksum=auth.password_checksum)
    if auth_res == "success":
        response = JSONResponse(content={"status": "success"})
        uid = str(uuid.uuid4())
        suid = ''.join(uid.split('-'))
        login_rec[suid] = crud.get_userinfo_by_name(db=db, username=auth.username).id
        response.set_cookie(key="login_id", value=suid)
        return response
    else:
        if login_id in login_rec and not login_rec[login_id] is None:
            login_rec[login_id] = None
        raise HTTPException(status_code=400, detail=auth_res)


# 登陆后页面跳转
@app.get("/login/redirect", response_class=HTMLResponse)
async def login_cookie(login_id: Optional[str] = Cookie(None)):
    print(login_id)
    if login_id in login_rec and not login_rec[login_id] is None:
        html = ""
        with open("html/login_success.html") as f:
            html = f.read()
        return html
    else:
        html = ""
        with open("html/login_failed.html") as f:
            html = f.read()
        return html


@app.get("/arrangement/add", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    return template.TemplateResponse('add_arrangement.html', {
        "request": request,
        "filelist": crud.get_files(db)
    })


@app.post("/arrangement/add")
async def add_arrangement(arrangement: schemas.ArrangementCreate, db: Session = Depends(get_db),
                          login_id: Optional[str] = Cookie(None)):
    arrangement.user_added = -1
    if login_id in login_rec:
        arrangement.user_added = login_rec[login_id]
    try:
        crud.create_arrangement(db=db, arrangement=arrangement)
        sche.add_job(filename=os.path.join(file_path, arrangement.file), timestamp=arrangement.begin_timestamp)
    except ValueError as valerr:
        raise HTTPException(status_code=400, detail=valerr.args)
    return arrangement


@app.get("/arrangement/get_event")
async def get_calendar_event(db: Session = Depends(get_db)):
    arrangements = crud.get_arrangement_planned(db)
    events = []
    if arrangements is None:
        return None
    for arrangement in arrangements:
        events.append(CalendarEvent(
            title=arrangement.title,
            start=arrangement.begin_timestamp.astimezone(
                pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%dT%H:%M:%S"),
            end=arrangement.end_timestamp.astimezone(pytz.timezone('Asia/Shanghai')).strftime(
                "%Y-%m-%dT%H:%M:%S")))
    return events


@app.get("/arrangement/get_cur", response_class=JSONResponse)
async def get_calendar_current(db: Session = Depends(get_db)):
    arrangement = crud.get_arrangement_current(db)
    if arrangement is None:
        return None
    return CalendarEvent(title=arrangement.title,
                         start=arrangement.begin_timestamp.astimezone(pytz.timezone('Asia/Shanghai')).strftime(
                             "%Y-%m-%dT%H:%M:%S"),
                         end=arrangement.end_timestamp.astimezone(pytz.timezone('Asia/Shanghai')).strftime(
                             "%Y-%m-%dT%H:%M:%S"))


@app.get("/arrangement/update")
async def update_arrangement(db: Session = Depends(get_db)):
    crud.update_arrangement(db)


@app.get("/upload", response_class=HTMLResponse)
async def file_upload(request: Request, db: Session = Depends(get_db)):
    return template.TemplateResponse('file_upload_page.html', {
        "request": request
    })


@app.post("/upload", status_code=201)
async def file_upload_post(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if file.content_type.find("audio") == -1 and file.content_type.find("video") == -1:
        raise HTTPException(status_code=400, detail="Invalid filetype")
    content = await file.read()
    with open(os.path.join(file_path, file.filename), "wb") as f:
        f.write(content)
    crud.create_file(db, schemas.FileCreate(
        filename=file.filename,
        user_upload=-1
    ))
    return {"filename": file.filename, "status": "succeeded"}


@app.post("/system/play")
async def play_audio(file: schemas.FilePlay, db: Session = Depends(get_db)):
    if crud.get_file_by_name(db=db, filename=file.filename) is None:
        raise HTTPException(status_code=400)
    try:
        async_play_thread = AudioProcess(filename=os.path.join(file_path, file.filename))
        async_play_thread.run()
    except:
        print("Error: unable to start thread")


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


@app.get("/home", response_class=HTMLResponse)
async def home_page(request: Request, db: Session = Depends(get_db)):
    arrangements = crud.get_arrangement_planned(db)
    cur_arrangement = crud.get_arrangement_current(db)
    return template.TemplateResponse('index.html', {
        "request": request,
        "arrangements": arrangements,
        "cur_arrangement": cur_arrangement,
        "dis_arrangements": arrangements[:5] if arrangements is not None else None
    })


@app.get("/submit_songs", response_class=HTMLResponse)
async def submit_songs(request: Request, db: Session = Depends(get_db)):
    arrangements = crud.get_arrangement_planned(db)
    cur_arrangement = crud.get_arrangement_current(db)
    return template.TemplateResponse('submit_songs.html', {
        "request": request,
        "arrangements": arrangements,
        "cur_arrangement": cur_arrangement
    })


@app.get("/submit_songs/song_info/", response_model=schemas.DownloadedSongResponse, response_class=JSONResponse)
async def get_song_info(shared_link: str, db: Session = Depends(get_db)):
    shared_link = parse.unquote(shared_link)
    t1 = threading.Thread(target=crud.ensure_downloaded_song_by_shared_link,args=[shared_link])
    t1.start()
    timeout = 60.0
    await asyncio.sleep(random.random()+3)
    while t1.is_alive() and timeout>0.0:
        print("waiting for thread")
        wait_time = random.random()
        timeout -= wait_time
        await asyncio.sleep(wait_time)
    downloaded_song = crud.get_downloaded_song_by_shared_link(db, shared_link)
    if downloaded_song is None:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail="Invalid Shared Link")
    return schemas.DownloadedSongResponse(
        title=downloaded_song.title,
        picture_link=downloaded_song.picture_link,
        artist=downloaded_song.artist
    )


@app.post("/submit_songs/accept")
async def accept_song_submit(song_submit_id: str = Form(...), db: Session = Depends(get_db)):
    songsubmit = crud.get_song_submit_by_id(db, song_submit_id)
    if songsubmit is None:
        raise HTTPException(400, "Song submit is None")
    t1 = threading.Thread(target=crud.accept_song_submit, args=[song_submit_id])
    t1.start()


@app.post("/submit_songs/reject")
async def reject_song_submit(song_submit_id: str = Form(...), db: Session = Depends(get_db)):
    songsubmit = crud.get_song_submit_by_id(db, song_submit_id)
    db.delete(songsubmit)
    db.commit()
    db.refresh(songsubmit)


@app.post("/submit_songs")
async def submit_songs_post(songsubmit: schemas.SongSubmit, db: Session = Depends(get_db)):
    songsubmit.shared_link = parse.unquote(songsubmit.shared_link)
    try:
        crud.create_song_submit(db=db, song_submit=songsubmit)
    except ValueError as valerr:
        raise HTTPException(status_code=400, detail=valerr.args)
    return songsubmit


@app.get("/arrangements", response_class=HTMLResponse)
async def arrangements(request: Request, db: Session = Depends(get_db)):
    arrangements = crud.get_arrangement_planned(db)
    cur_arrangement = crud.get_arrangement_current(db)
    return template.TemplateResponse('arrangements.html', {
        "request": request,
        "arrangements": arrangements,
        "cur_arrangement": cur_arrangement,
        "files": crud.get_files(db),
        "song_submit": crud.get_song_submit(db)
    })


@app.get("/feedback", response_class=HTMLResponse)
async def feedback(request: Request, db: Session = Depends(get_db)):
    return template.TemplateResponse('feedback.html', {
        "request": request,
        "now": datetime.datetime.utcnow()
    })


@app.get("/about_us", response_class=HTMLResponse)
async def about_us(request: Request, db: Session = Depends(get_db)):
    arrangements = crud.get_arrangement_planned(db)
    cur_arrangement = crud.get_arrangement_current(db)
    return template.TemplateResponse('about_us.html', {
        "request": request,
        "arrangements": arrangements,
        "cur_arrangement": cur_arrangement
    })


@app.get("/files", response_class=HTMLResponse)
async def files(request: Request, db: Session = Depends(get_db)):
    return template.TemplateResponse('files.html', {
        "request": request,
        "files": crud.get_files(db),
        "now": datetime.datetime.utcnow()
    })


@app.get("/files/refresh")
def files_init(db: Session = Depends(get_db)):
    try:
        file_lists = os.listdir(file_path)
        for filename in file_lists:
            if crud.get_file_by_name(db, filename) is None:
                crud.create_file(db, schemas.FileCreate(
                    filename=filename,
                    user_upload=1
                ))
    except Exception as e:
        traceback.print_exc()


@app.get("/system/init")
def system_init(db: Session = Depends(get_db)):
    sche.scheduler.remove_all_jobs('default')
    try:
        sche.scheduler.start()
    except SchedulerAlreadyRunningError:
        print("Scheduler already start")
    arrangements = crud.get_arrangement_planned(db=db)
    if arrangements is not None:
        for arrangement in arrangements:
            sche.add_job(filename=os.path.join(file_path, arrangement.file),
                         timestamp=arrangement.begin_timestamp)


@app.get("/system/stop")
def system_stop_audio():
    try:
        sche.scheduler.shutdown()
    except SchedulerNotRunningError:
        print("Already not running")
    AudioProcess.stop_all()


@app.get("/stream")
def start_streaming(request: Request):
    return template.TemplateResponse('audio_stream.html', {
        "request": request,
    })


@app.get("/files/get/{filename}")
def send_file(filename: str, db: Session = Depends(get_db)):
    print(filename)
    if crud.get_file_by_name(db=db, filename=filename) is None:
        raise HTTPException(status_code=400)
    return FileResponse(os.path.join(util.config.file_path,os.path.basename(filename)), filename=filename)


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
