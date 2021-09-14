import asyncio
import datetime
import logging
import os
import random
import threading
import time
import traceback
import uuid

import pytz
import sqlalchemy.exc
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, asc

import database
import util.thread_ctrl
from . import models, schemas
from util import hashUtil, audio, web_requests, schedulerUtil


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()


def create_user(db: Session, user: schemas.UserCreate):
    fake_hashed_password = user.password
    db_user = models.User(email=user.email, hashed_password=fake_hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_items(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Item).offset(skip).limit(limit).all()


def create_user_item(db: Session, item: schemas.ItemCreate, user_id: int):
    db_item = models.Item(**item.dict(), owner_id=user_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def create_userinfo(db: Session, userinfo: schemas.UserInfoCreate):
    hashed_password = userinfo.password_checksum
    db_user = models.UserInfo(username=userinfo.username, password_checksum=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_userinfo(db: Session, userInfo_id: int):
    return db.query(models.UserInfo).filter(models.UserInfo.id == userInfo_id).first()


def get_userinfo_by_name(db: Session, username: str):
    return db.query(models.UserInfo).filter(models.UserInfo.username == username).first()


def auth_user(db: Session, username: str, password_checksum: str):
    if not db.query(models.UserInfo).filter(
            models.UserInfo.username == username, models.UserInfo.password_checksum == password_checksum
    ).first() is None:
        return "success"
    elif not db.query(models.UserInfo).filter(
            models.UserInfo.username == username).first() is None:
        return "password incorrect"
    else:
        return "user not found"


def get_files(db: Session, skip: int = 0, limit: int = 100):
    files = db.query(models.File).offset(skip).limit(limit).all()
    return files


def get_song_submit(db: Session, skip: int = 0, limit: int = 100):
    song_submit = db.query(models.SongSubmit).filter(models.SongSubmit.is_proceeded == False).offset(skip).limit(
        limit).all()
    return song_submit


def get_file_by_name(db: Session, filename: str):
    return db.query(models.File).filter(
        models.File.filename == filename
    ).first()


def get_file_by_checksum(db: Session, checksum: str):
    return db.query(models.File).filter(
        models.File.checksum == checksum
    ).first()


def create_file(db: Session, file: schemas.FileCreate):
    if not db.query(models.File).filter(models.File.filename == file.filename).first() is None:
        return None
    db_file = models.File(
        filename=file.filename,
        checksum=hashUtil.get_md5_from_local_file(file.filename),
        duration=audio.get_audio_duration(file.filename),
        user_upload=file.user_upload
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file


def get_arrangement_planned(db: Session,limit: int = 100):
    res_arrangements = db.query(models.Arrangement).filter(
        and_(models.Arrangement.is_valid == True,
             models.Arrangement.begin_timestamp > datetime.datetime.utcnow()
             )).order_by(asc(models.Arrangement.begin_timestamp)).limit(limit).all()
    if res_arrangements == []:
        return None
    for arrangement in res_arrangements:
        if arrangement.begin_timestamp.tzinfo is None:
            arrangement.begin_timestamp = arrangement.begin_timestamp.replace(tzinfo=pytz.timezone("UTC"))
        if arrangement.end_timestamp.tzinfo is None:
            arrangement.end_timestamp = arrangement.end_timestamp.replace(tzinfo=pytz.timezone("UTC"))
    return res_arrangements


def get_arrangement_current(db: Session):
    arrangement = db.query(models.Arrangement).filter(
        and_(models.Arrangement.is_valid == True,
             models.Arrangement.begin_timestamp <= datetime.datetime.utcnow(),
             models.Arrangement.end_timestamp > datetime.datetime.utcnow()
             )).first()
    if arrangement is None:
        return None
    if arrangement.begin_timestamp.tzinfo is None:
        arrangement.begin_timestamp = arrangement.begin_timestamp.replace(tzinfo=pytz.timezone("UTC"))
    if arrangement.end_timestamp.tzinfo is None:
        arrangement.end_timestamp = arrangement.end_timestamp.replace(tzinfo=pytz.timezone("UTC"))
    return arrangement


def create_arrangement(db: Session, arrangement: schemas.ArrangementCreate, auto_fix: bool = False):
    file = db.query(models.File).filter(
        models.File.filename == arrangement.file
    ).first()
    if file is None:
        print("No file")
        raise ValueError("Invalid filename")
    audio_file_duration = datetime.timedelta(seconds=audio.get_audio_duration(arrangement.file))
    end_timestamp = arrangement.begin_timestamp + audio_file_duration
    time.sleep(random.random())
    util.thread_ctrl.arrangement_db_access.acquire()
    if not db.query(models.Arrangement).filter(
            or_(
                and_(
                    models.Arrangement.begin_timestamp <= end_timestamp,
                    models.Arrangement.begin_timestamp >= arrangement.begin_timestamp,
                    models.Arrangement.is_valid == True
                ),
                and_(
                    models.Arrangement.end_timestamp <= end_timestamp,
                    models.Arrangement.end_timestamp >= arrangement.begin_timestamp,
                    models.Arrangement.is_valid == True
                )
            )
    ).first() is None:
        if auto_fix == False:
            raise ValueError("Invalid timestamp")
        else:
            db_arrangements = db.query(models.Arrangement).filter(
                models.Arrangement.end_timestamp > datetime.datetime.utcnow()
            ).order_by(asc(models.Arrangement.begin_timestamp)).all()
            is_timestamp_set = False
            former_arrangement = db_arrangements[0]
            for latter_arrangement in db_arrangements:
                if former_arrangement == latter_arrangement:
                    continue
                if latter_arrangement.begin_timestamp + audio_file_duration <= former_arrangement.end_timestamp:
                    arrangement.begin_timestamp = former_arrangement.end_timestamp
                    is_timestamp_set = True
                    break
                else:
                    former_arrangement = latter_arrangement
                    continue
            if not is_timestamp_set:
                arrangement.begin_timestamp = former_arrangement.end_timestamp
    db_arrangmement = models.Arrangement(**arrangement.dict())
    db_arrangmement.end_timestamp = arrangement.begin_timestamp + audio_file_duration
    db.add(db_arrangmement)
    file.last_arranged = db_arrangmement.end_timestamp
    db.commit()
    db.refresh(db_arrangmement)
    db.refresh(file)
    time.sleep(random.random())
    util.thread_ctrl.arrangement_db_access.release()
    print("Arrangement created: begins at "+db_arrangmement.begin_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
    return db_arrangmement


def update_arrangement(db: Session):
    db_arrangements = db.query(models.Arrangement).filter(
        models.Arrangement.end_timestamp < datetime.datetime.utcnow()
    ).all()
    for arr in db_arrangements:
        arr.is_valid = False
    db.commit()
    db.refresh(db_arrangements)
    return db_arrangements.count()


def accept_song_submit(song_submit_id):
    time.sleep(random.random())
    util.thread_ctrl.accept_song_submit_mutex.acquire()
    try:
        db = database.get_db_subthread()
    except Exception:
        print("Create db session error")
        raise SystemError()
    print("In accept song submit")
    song_submit = get_song_submit_by_id(db, song_submit_id)
    print(song_submit.fk_downloaded_song)
    print("Get song_submit completed")
    exp_file = uuid.uuid3(
        namespace=uuid.NAMESPACE_DNS,
        name=song_submit.fk_downloaded_song+song_submit.name+song_submit.message
    ).hex[0:8]+".mp3"
    db_file = db.query(models.File).filter(models.File.filename == exp_file).first()
    print("Get file completed")
    if db_file is None:
        if song_submit.downloaded_song.filename == "Content Not Local":
            try:
                song_info = web_requests.download_from_song_info(song_submit.downloaded_song)
            except ValueError:
                song_info = web_requests.get_song_info(song_submit.downloaded_song.shared_link,db)
                try:
                    song_info = web_requests.download_from_song_info(song_info)
                except ValueError:
                    raise ValueError("Invalid sharedlink")
            song_submit.downloaded_song.filename = song_info.filename
        create_file(db, schemas.FileCreate(
            filename=song_submit.downloaded_song.filename,
            user_upload=999
        ))
        print("Create file completed")
        if song_submit.name is None or song_submit.name == "":
            filename = audio.join_speech("下面为大家带来一首" + song_submit.downloaded_song.title,
                                         song_submit.downloaded_song.filename, exp_file)
        else:
            if song_submit.message is None or song_submit.message == "":
                filename = audio.join_speech("下面由" + song_submit.name + "为大家带来一首" + song_submit.downloaded_song.title,
                                             song_submit.downloaded_song.filename, exp_file)
            else:
                filename = audio.join_speech("下面由" + song_submit.name + "为大家带来一首" + song_submit.downloaded_song.title +
                                             "，他想说" + song_submit.message, song_submit.downloaded_song.filename,
                                             exp_file)
        create_file(db, schemas.FileCreate(
            filename=filename,
            user_upload=999
        ))
    else:
        filename = db_file.filename
    print("Creating agenda")
    try:
        new_filename = filename
        songsubmit = song_submit
        if songsubmit.expDatetime.year==1970:
            songsubmit.expDatetime = datetime.datetime.utcnow() + datetime.timedelta(seconds=1)
        songsubmit.expDatetime = songsubmit.expDatetime.replace(tzinfo=pytz.timezone("UTC"))
        print("Calculated begin_timestamp")
        util.thread_ctrl.arrangement_db_access.release()
        db_arrangement = create_arrangement(db, arrangement=schemas.ArrangementCreate(
            begin_timestamp=songsubmit.expDatetime,
            file=new_filename,
            is_valid=True,
            user_added=999,
            title=songsubmit.downloaded_song.title,
            abstract=songsubmit.message
        ),auto_fix=True)
        util.thread_ctrl.arrangement_db_access.acquire()
    except Exception:
        traceback.print_exc()
        raise ValueError("Database error")
    print("Add arrangement completed")
    schedulerUtil.sche.add_job(filename=db_arrangement.file,
                 timestamp=db_arrangement.begin_timestamp + datetime.timedelta(hours=8))
    print("Add schedule completed")
    songsubmit.is_proceeded = True
    db.commit()
    db.refresh(songsubmit)
    db.refresh(db_arrangement)
    time.sleep(0.1)
    time.sleep(random.random())
    util.thread_ctrl.accept_song_submit_mutex.release()
    print("Accept success")


def create_song_submit(db: Session, song_submit: schemas.SongSubmit):
    print("------- Creating song submit ------")
    song_info = get_downloaded_song_by_shared_link(db, song_submit.shared_link)
    if song_info is None:
        raise ValueError("Invalid Link")
    db.commit()
    db.refresh(song_info)
    db_song_submit = models.SongSubmit(**song_submit.dict())
    try:
        db_song_submit.id = uuid.uuid3(
            namespace=uuid.NAMESPACE_DNS,
            name=db_song_submit.email + song_info.key + db_song_submit.expDatetime.strftime("%Y-%m-%d %H:%M:%S")
        ).hex[0:8]
        db_song_submit.fk_downloaded_song = song_info.key
        db.add(db_song_submit)
        db.commit()
        db.refresh(db_song_submit)
    except sqlalchemy.exc.IntegrityError:
        raise ValueError("Concurrent with current song submit")


def get_song_submit_by_id(db: Session, song_submit_id: str):
    db_song_submit = db.query(models.SongSubmit).filter(
        and_(
            models.SongSubmit.id == song_submit_id,
            models.SongSubmit.is_proceeded == False
        )
    ).first()
    return db_song_submit


def get_downloaded_song_by_shared_link(db: Session, shared_link: str):
    db_song = db.query(models.DownloadedSong).filter(
        models.DownloadedSong.shared_link == shared_link
    ).first()
    return db_song


def ensure_downloaded_song_by_shared_link(shared_link: str):
    try:
        db = database.get_db_subthread()
    except Exception:
        print("Create db session error")
        raise SystemError()
    db_song = db.query(models.DownloadedSong).filter(
        models.DownloadedSong.shared_link == shared_link
    ).first()
    if db_song is None:
        print("create thread")
        t1 = threading.Thread(target=web_requests.get_song_info,args=[shared_link, db, True])
        t1.start()
    return


def get_song_info_callback(db: Session,db_song:models.DownloadedSong):
    if db_song is None:
        return
    db_song_old = db.query(models.DownloadedSong).filter(
        models.DownloadedSong.key == db_song.key
    ).first()
    if db_song_old is None or db_song_old.filename == "Content Not Local":
        db.query(models.DownloadedSong).filter(
            models.DownloadedSong.key == db_song.key
        ).delete()
        db.add(db_song)
        db.commit()
        db.refresh(db_song)
