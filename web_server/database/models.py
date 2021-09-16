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
from sqlalchemy import *
from sqlalchemy.orm import relationship, Session
from sqlalchemy.exc import IntegrityError

from . import schemas, Base
from .. import database
from ..util import hashUtil, audio, web_requests, schedulerUtil, thread_ctrl


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)

    items = relationship("Item", back_populates="owner")


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="items")


class UserInfo(Base):
    __tablename__ = 'User'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_checksum = Column(String, default='666666')

    @classmethod
    def create(cls, db: Session, userinfo: schemas.UserInfoCreate):
        hashed_password = userinfo.password_checksum
        db_user = cls(username=userinfo.username, password_checksum=hashed_password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @classmethod
    def get_by_id(cls, db: Session, userInfo_id: int):
        return db.query(cls).filter(cls.id == userInfo_id).first()

    @classmethod
    def get_by_name(cls, db: Session, username: str):
        return db.query(cls).filter(cls.username == username).first()

    @classmethod
    def auth(cls, db: Session, username: str, password_checksum: str):
        if not db.query(cls).filter(
                cls.username == username, cls.password_checksum == password_checksum
        ).first() is None:
            return "success"
        elif not db.query(cls).filter(
                cls.username == username).first() is None:
            return "password incorrect"
        else:
            return "user not found"


class File(Base):
    __tablename__ = 'File'
    filename = Column(String, primary_key=True, index=True)
    checksum = Column(String, index=True)
    duration = Column(Float(precision=10))
    last_arranged = Column(DateTime(timezone=True))

    user_upload = Column(Integer, ForeignKey("User.id"))

    arrangement = relationship("Arrangement", back_populates="audio_file")
    downloaded_song = relationship("DownloadedSong", back_populates="file")

    @classmethod
    def get(cls, db: Session, skip: int = 0, limit: int = 100):
        files = db.query(cls).offset(skip).limit(limit).all()
        return files

    @classmethod
    def get_by_name(cls, db: Session, filename: str):
        return db.query(cls).filter(
            cls.filename == filename
        ).first()

    @classmethod
    def get_by_checksum(cls, db: Session, checksum: str):
        return db.query(cls).filter(
            cls.checksum == checksum
        ).first()

    @classmethod
    def create(cls, db: Session, file: schemas.FileCreate):
        if not db.query(cls).filter(cls.filename == file.filename).first() is None:
            return None
        db_file = cls(
            filename=file.filename,
            checksum=hashUtil.get_md5_from_local_file(file.filename),
            duration=audio.get_audio_duration(file.filename),
            user_upload=file.user_upload
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        return db_file


class Arrangement(Base):
    __tablename__ = 'Arrangement'
    id = Column(Integer, primary_key=True)
    begin_timestamp = Column(DateTime(timezone=True))
    end_timestamp = Column(DateTime(timezone=True))
    file = Column(String, ForeignKey("File.filename"), nullable=True)
    is_valid = Column(Boolean, default=True)
    user_added = Column(String, ForeignKey("User.id"))
    title = Column(String)
    abstract = Column(String)

    audio_file = relationship("File", back_populates="arrangement")

    @classmethod
    def get_planned(cls, db: Session, limit: int = 100):
        res_arrangements = db.query(cls).filter(
            and_(cls.is_valid == True,
                 cls.begin_timestamp > datetime.datetime.utcnow()
                 )).order_by(asc(cls.begin_timestamp)).limit(limit).all()
        if res_arrangements == []:
            return None
        for arrangement in res_arrangements:
            if arrangement.begin_timestamp.tzinfo is None:
                arrangement.begin_timestamp = arrangement.begin_timestamp.replace(tzinfo=pytz.timezone("UTC"))
            if arrangement.end_timestamp.tzinfo is None:
                arrangement.end_timestamp = arrangement.end_timestamp.replace(tzinfo=pytz.timezone("UTC"))
        return res_arrangements

    @classmethod
    def get_current(cls, db: Session):
        arrangement = db.query(cls).filter(
            and_(cls.is_valid == True,
                 cls.begin_timestamp <= datetime.datetime.utcnow(),
                 cls.end_timestamp > datetime.datetime.utcnow()
                 )).first()
        if arrangement is None:
            return None
        if arrangement.begin_timestamp.tzinfo is None:
            arrangement.begin_timestamp = arrangement.begin_timestamp.replace(tzinfo=pytz.timezone("UTC"))
        if arrangement.end_timestamp.tzinfo is None:
            arrangement.end_timestamp = arrangement.end_timestamp.replace(tzinfo=pytz.timezone("UTC"))
        return arrangement

    @classmethod
    def create(cls, db: Session, arrangement: schemas.ArrangementCreate, auto_fix: bool = False):
        file = File.get_by_name(db, arrangement.file)
        if file is None:
            print("No file")
            raise ValueError("Invalid filename")
        audio_file_duration = datetime.timedelta(seconds=audio.get_audio_duration(arrangement.file))
        end_timestamp = arrangement.begin_timestamp + audio_file_duration
        time.sleep(random.random())
        thread_ctrl.arrangement_db_access.acquire()
        if not db.query(cls).filter(
                or_(
                    and_(
                        cls.begin_timestamp <= end_timestamp,
                        cls.begin_timestamp >= arrangement.begin_timestamp,
                        cls.is_valid == True
                    ),
                    and_(
                        cls.end_timestamp <= end_timestamp,
                        cls.end_timestamp >= arrangement.begin_timestamp,
                        cls.is_valid == True
                    )
                )
        ).first() is None:
            if auto_fix == False:
                raise ValueError("Invalid timestamp")
            else:
                db_arrangements = db.query(cls).filter(
                    cls.end_timestamp > datetime.datetime.utcnow()
                ).order_by(asc(cls.begin_timestamp)).all()
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
        db_arrangmement = cls(**arrangement.dict())
        db_arrangmement.end_timestamp = arrangement.begin_timestamp + audio_file_duration
        db.add(db_arrangmement)
        file.last_arranged = db_arrangmement.end_timestamp
        db.commit()
        db.refresh(db_arrangmement)
        db.refresh(file)
        time.sleep(random.random())
        thread_ctrl.arrangement_db_access.release()
        print("Arrangement created: begins at " + db_arrangmement.begin_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        return db_arrangmement

    @classmethod
    def update(cls, db: Session):
        db_arrangements = db.query(cls).filter(
            cls.end_timestamp < datetime.datetime.utcnow()
        ).all()
        for arr in db_arrangements:
            arr.is_valid = False
        db.commit()
        db.refresh(db_arrangements)
        return db_arrangements.count()


class SongSubmit(Base):
    __tablename__ = 'SongSubmit'
    id = Column(String, primary_key=True)
    shared_link = Column(String)
    expDatetime = Column(DateTime(timezone=True))
    email = Column(String)
    name = Column(String)
    message = Column(String)
    is_proceeded = Column(Boolean, default=False)

    fk_downloaded_song = Column(String, ForeignKey("DownloadedSong.key"))

    downloaded_song = relationship("DownloadedSong", back_populates="song_submit")

    @classmethod
    def get(cls, db: Session, skip: int = 0, limit: int = 100):
        song_submit = db.query(cls).filter(cls.is_proceeded == False).offset(skip).limit(
            limit).all()
        return song_submit

    @classmethod
    def accept(cls, song_submit_id):
        time.sleep(random.random())
        thread_ctrl.accept_song_submit_mutex.acquire()
        try:
            db = database.get_db_subthread()
        except Exception:
            print("Database Error: cannot create db_session in thread accept_song_submit")
            raise SystemError("Database Error: cannot create db_session in thread accept_song_submit")
        print("In accept song submit")
        song_submit = cls.get_by_id(db, song_submit_id)
        print(song_submit.fk_downloaded_song)
        print("Get song_submit completed")
        db_arrangement = Arrangement.create(db, arrangement=schemas.ArrangementCreate(
            begin_timestamp=song_submit.expDatetime,
            file=None,
            is_valid=True,
            user_added=999,
            title=song_submit.downloaded_song.title,
            abstract=song_submit.message
        ), auto_fix=True)
        exp_file = uuid.uuid3(
            namespace=uuid.NAMESPACE_DNS,
            name=song_submit.fk_downloaded_song + song_submit.name + song_submit.message
        ).hex[0:8] + ".mp3"
        db_file = File.get_by_name(db,exp_file)
        print("Get file completed")
        if db_file is None:
            if song_submit.downloaded_song.filename == "Content Not Local":
                try:
                    song_info = web_requests.download_from_song_info(song_submit.downloaded_song)
                except ValueError:
                    song_info = web_requests.get_song_info(song_submit.downloaded_song.shared_link, db)
                    try:
                        song_info = web_requests.download_from_song_info(song_info)
                    except ValueError:
                        raise ValueError("Invalid sharedlink")
                song_submit.downloaded_song.filename = song_info.filename
            File.create(db,schemas.FileCreate(
                filename=song_submit.downloaded_song.filename,
                user_upload=999
            ))
            print("Create file completed")
            if song_submit.name is None or song_submit.name == "":
                filename = audio.join_speech("下面为大家带来一首" + song_submit.downloaded_song.title,
                                             song_submit.downloaded_song.filename, exp_file)
            else:
                if song_submit.message is None or song_submit.message == "":
                    filename = audio.join_speech(
                        "下面由" + song_submit.name + "为大家带来一首" + song_submit.downloaded_song.title,
                        song_submit.downloaded_song.filename, exp_file)
                else:
                    filename = audio.join_speech(
                        "下面由" + song_submit.name + "为大家带来一首" + song_submit.downloaded_song.title +
                        "，他想说" + song_submit.message, song_submit.downloaded_song.filename,
                        exp_file)
            File.create(db, schemas.FileCreate(
                filename=filename,
                user_upload=999
            ))
        else:
            filename = db_file.filename
        print("Creating agenda")
        try:
            new_filename = filename
            songsubmit = song_submit
            if songsubmit.expDatetime.year == 1970:
                songsubmit.expDatetime = datetime.datetime.utcnow() + datetime.timedelta(seconds=1)
            songsubmit.expDatetime = songsubmit.expDatetime.replace(tzinfo=pytz.timezone("UTC"))
            print("Calculated begin_timestamp")
            thread_ctrl.arrangement_db_access.release()
            db_arrangement = Arrangement.create(db, arrangement=schemas.ArrangementCreate(
                begin_timestamp=songsubmit.expDatetime,
                file=new_filename,
                is_valid=True,
                user_added=999,
                title=songsubmit.downloaded_song.title,
                abstract=songsubmit.message
            ), auto_fix=True)
            thread_ctrl.arrangement_db_access.acquire()
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
        thread_ctrl.accept_song_submit_mutex.release()
        print("Accept success")

    @classmethod
    def create(cls, db: Session, song_submit: schemas.SongSubmit):
        print("------- Creating song submit ------")
        song_info = DownloadedSong.get_by_shared_link(db, song_submit.shared_link)
        if song_info is None:
            raise ValueError("Invalid Link")
        db.commit()
        db.refresh(song_info)
        db_song_submit = cls(**song_submit.dict())
        try:
            db_song_submit.id = uuid.uuid3(
                namespace=uuid.NAMESPACE_DNS,
                name=db_song_submit.email + song_info.key + db_song_submit.expDatetime.strftime("%Y-%m-%d %H:%M:%S")
            ).hex[0:8]
            db_song_submit.fk_downloaded_song = song_info.key
            db.add(db_song_submit)
            db.commit()
            db.refresh(db_song_submit)
        except IntegrityError:
            raise ValueError("Concurrent with current song submit")

    @classmethod
    def get_by_id(cls, db: Session, song_submit_id: str):
        db_song_submit = db.query(cls).filter(
            and_(
                cls.id == song_submit_id,
                cls.is_proceeded == False
            )
        ).first()
        return db_song_submit


class DownloadedSong(Base):
    __tablename__ = 'DownloadedSong'
    key = Column(String, primary_key=True, index=True)
    filename = Column(String, ForeignKey("File.filename"))
    picture_link = Column(String)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    shared_link = Column(String, index=True)
    download_link = Column(String, index=True)

    file = relationship("File", back_populates="downloaded_song")
    song_submit = relationship("SongSubmit", back_populates="downloaded_song")

    @classmethod
    def get_by_shared_link(cls, db: Session, shared_link: str):
        db_song = db.query(cls).filter(
            cls.shared_link == shared_link
        ).first()
        return db_song

    @classmethod
    def ensure_by_shared_link(cls, shared_link: str):
        try:
            db = database.get_db_subthread()
        except Exception:
            print("Create db session error")
            raise SystemError()
        db_song = db.query(cls).filter(
            cls.shared_link == shared_link
        ).first()
        if db_song is None:
            print("create thread")
            t1 = threading.Thread(target=web_requests.get_song_info, args=[shared_link, db, True])
            t1.start()
        return
