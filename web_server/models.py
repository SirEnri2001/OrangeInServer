from __future__ import annotations
import datetime
import random
import threading
import time
import traceback
import uuid
import pytz
import json
import os
import urllib.request
import requests
from urllib.error import HTTPError
from music_dl.addons import netease, qq
from sqlalchemy import *
from sqlalchemy.orm import relationship, Session
from sqlalchemy.exc import IntegrityError
from database import get_db_subthread
from database import Base
import schemas
import hashUtil, audio, thread_ctrl, schedulerUtil


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
    def get_by_id(cls, db: Session, userinfo_id: int):
        return db.query(cls).filter(cls.id == userinfo_id).first()

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
    def get_planned(cls, db: Session, limit: int = 100) -> list[Arrangement]:
        res_arrangements = db.query(cls).filter(
            and_(cls.is_valid is True,
                 cls.begin_timestamp > datetime.datetime.utcnow()
                 )).order_by(asc(cls.begin_timestamp)).limit(limit).all()
        if not res_arrangements:
            return []
        for arrangement in res_arrangements:
            if arrangement.begin_timestamp.tzinfo is None:
                arrangement.begin_timestamp = arrangement.begin_timestamp.replace(tzinfo=pytz.timezone("UTC"))
            if arrangement.end_timestamp.tzinfo is None:
                arrangement.end_timestamp = arrangement.end_timestamp.replace(tzinfo=pytz.timezone("UTC"))
        return res_arrangements

    @classmethod
    def get_current(cls, db: Session) -> Arrangement | None:
        arrangement = db.query(cls).filter(
            and_(cls.is_valid is True,
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
    def create(cls, db: Session, arrangement: schemas.ArrangementCreate, exclusive: bool = False):
        file = None
        if arrangement.file is not None:
            file = File.get_by_name(db, arrangement.file)
            if file is None:
                print("ERROR creating arrangement: No such file")
                raise ValueError("Invalid filename")
        audio_file_duration = datetime.timedelta(seconds=audio.get_audio_duration(arrangement.file))
        end_timestamp = arrangement.begin_timestamp + audio_file_duration
        time.sleep(random.random())
        # thread_ctrl.arrangement_db_access.acquire()
        if not db.query(cls).filter(
                or_(
                    and_(
                        cls.begin_timestamp <= end_timestamp,
                        cls.begin_timestamp >= arrangement.begin_timestamp,
                        cls.is_valid is True
                    ),
                    and_(
                        cls.end_timestamp <= end_timestamp,
                        cls.end_timestamp >= arrangement.begin_timestamp,
                        cls.is_valid is True
                    )
                )
        ).first() is None:
            if exclusive:
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
        if file is not None:
            file.last_arranged = db_arrangmement.end_timestamp
        db.commit()
        db.refresh(db_arrangmement)
        if file is not None:
            db.refresh(file)
        # thread_ctrl.arrangement_db_access.release()
        print("Arrangement created: begins at " + db_arrangmement.begin_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        return db_arrangmement

    @classmethod
    def refresh(cls, db: Session):
        db_arrangements = db.query(cls).filter(
            cls.end_timestamp < datetime.datetime.utcnow()
        ).all()
        for arr in db_arrangements:
            arr.is_valid = False
        db.commit()
        db.refresh(db_arrangements)
        return db_arrangements.count()

    def update_file(self, db: Session, file: File):
        self.file = file.filename
        db.commit()
        db.refresh(self)
        db.refresh(file)

    def to_calendar_event(self) -> schemas.CalendarEvent:
        return schemas.CalendarEvent(
            title=self.title,
            start=self.begin_timestamp.astimezone(
                pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%dT%H:%M:%S"),
            end=self.end_timestamp.astimezone(pytz.timezone('Asia/Shanghai')).strftime(
                "%Y-%m-%dT%H:%M:%S"))


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
        song_submit = db.query(cls).filter(cls.is_proceeded is False).offset(skip).limit(
            limit).all()
        return song_submit

    @classmethod
    def accept(cls, song_submit_id):
        time.sleep(random.random())
        thread_ctrl.accept_song_submit_mutex.acquire()
        try:
            db = get_db_subthread()
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
        ), exclusive=False)
        exp_file = uuid.uuid3(
            namespace=uuid.NAMESPACE_DNS,
            name=song_submit.fk_downloaded_song + song_submit.name + song_submit.message
        ).hex[0:8] + ".mp3"
        db_file = File.get_by_name(db, exp_file)
        print("Get file completed")
        if db_file is None:
            if song_submit.downloaded_song.filename == "Content Not Local":
                try:
                    song_info = song_submit.downloaded_song.download_from_song_info(song_submit.downloaded_song)
                except ValueError:
                    song_info = DownloadedSong.get_by_shared_link(song_submit.downloaded_song.shared_link, db, True)
                    try:
                        song_info = song_info.download_from_song_info()
                    except ValueError:
                        raise ValueError("Invalid sharedlink")
                song_submit.downloaded_song.filename = song_info.filename
            File.create(db, schemas.FileCreate(
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
            db_arrangement.file = new_filename
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
        song_info = DownloadedSong.get_by_shared_link(song_submit.shared_link, db)
        if song_info is None:
            raise ValueError("Invalid Link")
        db_song_submit = cls(**song_submit.dict())
        try:
            db_song_submit.id = uuid.uuid3(
                namespace=uuid.NAMESPACE_DNS,
                name=db_song_submit.email + song_info.key + db_song_submit.expDatetime.strftime("%Y-%m-%d %H:%M:%S")
            ).hex[0:8]
            db_song_submit.fk_downloaded_song = song_info.key
            db.add(db_song_submit)
            db.commit()
            db.refresh(song_info)
            db.refresh(db_song_submit)
        except IntegrityError:
            raise ValueError("Concurrent with current song submit")


    @classmethod
    def get_by_id(cls, db: Session, song_submit_id: str):
        db_song_submit = db.query(cls).filter(
            and_(
                cls.id == song_submit_id,
                cls.is_proceeded is False
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
    def get_by_key(cls, db: Session, key: str):
        db_song = db.query(cls).filter(
            cls.key == key
        ).first()
        return db_song

    @classmethod
    def ensure_by_shared_link(cls, shared_link: str):
        try:
            db = get_db_subthread()
        except Exception:
            print("Create db session error")
            raise SystemError()
        t1 = threading.Thread(target=DownloadedSong.get_by_shared_link, args=[shared_link, db, True])
        t1.start()
        return

    @classmethod
    def get_by_shared_link(cls, shared_link: str, db: Session, update_old: bool = False):
        db_song = db.query(cls).filter(
            cls.shared_link == shared_link
        ).first()
        if db_song is not None:
            return db_song
        db_song_info = _get_song_info(shared_link)
        if update_old:
            db_song_old = DownloadedSong.get_by_key(db, db_song_info.key)
            if db_song_old is None or db_song_old.filename == "Content Not Local":
                if db_song_old is not None:
                    db_song_old.delete()
                db.add(db_song_info)
                db.commit()
                db.refresh(db_song_info)
        return db_song_info

    def download_from_song_info(self):
        try:
            print("Retrieve song file from url: " + self.download_link)
            self.filename = self.download_link.split('/')[-1].split('?')[0]
            urllib.request.urlretrieve(
                self.download_link
                , os.path.join(audio.file_path, self.filename))
        except urllib.error.HTTPError:
            raise ValueError("Need for retry")
        if self.filename.split(".")[-1].find("m4a") != -1:
            self.filename = audio.m4a_to_mp3(self.filename)
        return self


user_agent_list = [
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.99 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; …) Gecko/20100101 Firefox/61.0",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.186 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.62 Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/45.0.2454.101 Safari/537.36",
    "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0)",
    "Mozilla/5.0 (Macintosh; U; PPC Mac OS X 10.5; en-US; rv:1.9.2.15) Gecko/20110303 Firefox/3.6.15",
]

caps = {
    'browserName': 'chrome',
    'version': '',
    'platform': 'ANY',
    'goog:loggingPrefs': {'performance': 'ALL'},  # 记录性能日志
    'goog:chromeOptions': {'extensions': [], 'args': [
        '--headless',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        'blink-settings=imagesEnabled=false',
        '--disable-gpu',
        'Connection=close']}  # 无界面模式
}


def _get_song_info(shared_link: str):
    print("Get song shared link: " + shared_link)
    # 根据用户提交的分享链接类型判断QQ还是网易云音乐
    if shared_link.find("music.163.com") != -1:
        song_info = _get_song_info_netease(shared_link)
    elif shared_link.find("y.qq.com") != -1:
        song_info = _get_song_info_qq(shared_link)
    else:
        return None
    return song_info


def _get_song_info_qq(shared_link: str):
    if not shared_link.find("/songDetail/") == -1:
        mid = shared_link[shared_link.find("songDetail/") + 11:len(shared_link)]
    else:
        # 通过分享链接获取mid
        print("requests get: " + shared_link)
        res = requests.get(shared_link)
        mid = res.text.split('mid&#61;')[1].split('&#38;')[0]
    print(mid)
    if mid is None:
        return
    # 获取歌曲标题、歌手、专辑封面等信息
    print("requests get: " + 'songDetail/' + mid)
    res = requests.get("https://y.qq.com/n/ryqq/songDetail/" + mid)
    _res_list = res.text.split('window.__INITIAL_DATA__ ={"detail":{')[1].split("}")[0].split('"title":"')
    title = _res_list[1].split('"')[0]
    artist = _res_list[2].split('"')[0]
    pic_link = "http://y.qq.com" + \
               res.text.split("window.__INITIAL_DATA__ ={")[1].split("?max_age=")[0].split('y.qq.com')[1].encode(
                   'utf-8').decode("unicode_escape")
    song_title = title
    song_artist = artist
    # 获取QQ音乐文件本地下载链接
    res = requests.get(
        "https://u.y.qq.com/cgi-bin/musicu.fcg?format=json&data=%7B%22req_0%22:%7B%22"
        "module%22:%22vkey.GetVkeyServer%22,%22method%22:%22CgiGetVkey%22,%22param%22:%7B%22"
        "guid%22:%22358840384%22,%22songmid%22:%5B%22"
        + mid +
        "%22%5D,%22songtype%22:%5B0%5D,%22uin%22:%221443481947%22,%22"
        "loginflag%22:1,%22platform%22:%2220%22%7D%7D,%22comm%22:%7B%22uin%22:%2218585073516%22,%22"
        "format%22:%22json%22,%22ct%22:24,%22cv%22:0%7D%7D")
    json_res = json.loads(res.text)
    print("https://isure.stream.qqmusic.qq.com/" +
          json_res['req_0']['data']['midurlinfo'][0]['purl'])
    return DownloadedSong(
        filename="Content Not Local",
        key=mid,
        picture_link=pic_link,
        title=song_title,
        artist=song_artist,
        shared_link=shared_link,
        download_link="https://isure.stream.qqmusic.qq.com/" +
                      json_res['req_0']['data']['midurlinfo'][0]['purl']
    )


def _get_song_info_netease(shared_link: str):
    print(shared_link)
    md_info = netease.netease_single(shared_link)
    """ Download song from netease music """
    data = netease.NeteaseApi.encrypted_request(dict(ids=[md_info.id], br=32000))
    res_data = netease.NeteaseApi.request(
        "http://music.163.com/weapi/song/enhance/player/url",
        method="POST",
        data=data,
    ).get("data", [])

    if len(res_data) > 0:
        md_info.song_url = res_data[0].get("url", "")
        md_info.rate = int(res_data[0].get("br", 0) / 1000)
    return DownloadedSong(
        filename="Content Not Local",
        key=md_info.id,
        picture_link=md_info.cover_url,
        title=md_info.title,
        artist=md_info.singer,
        shared_link=shared_link,
        download_link=md_info.song_url
    )

