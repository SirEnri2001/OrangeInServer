from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Time, DateTime, Float
from sqlalchemy.orm import relationship

from . import Base


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
    password_checksum = Column(String,default='666666')


class File(Base):
    __tablename__ = 'File'
    filename = Column(String,primary_key=True,index=True)
    checksum = Column(String,index=True)
    duration = Column(Float(precision=10))
    last_arranged = Column(DateTime(timezone=True))

    user_upload = Column(Integer, ForeignKey("User.id"))

    arrangement = relationship("Arrangement",back_populates="audio_file")
    downloaded_song = relationship("DownloadedSong", back_populates="file")


class Arrangement(Base):
    __tablename__ = 'Arrangement'
    id = Column(Integer,primary_key=True)
    begin_timestamp = Column(DateTime(timezone=True))
    end_timestamp = Column(DateTime(timezone=True))
    file = Column(String, ForeignKey("File.filename"))
    is_valid = Column(Boolean, default=True)
    user_added = Column(String, ForeignKey("User.id"))
    title = Column(String)
    abstract = Column(String)

    audio_file = relationship("File",back_populates="arrangement")


class SongSubmit(Base):
    __tablename__ = 'SongSubmit'
    id = Column(String,primary_key=True)
    shared_link = Column(String)
    expDatetime = Column(DateTime(timezone=True))
    email = Column(String)
    name = Column(String)
    message = Column(String)
    is_proceeded = Column(Boolean,default=False)

    fk_downloaded_song = Column(String,ForeignKey("DownloadedSong.key"))

    downloaded_song = relationship("DownloadedSong",back_populates="song_submit")


class DownloadedSong(Base):
    __tablename__ = 'DownloadedSong'
    key = Column(String, primary_key=True, index=True)
    filename = Column(String,ForeignKey("File.filename"))
    picture_link = Column(String)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    shared_link = Column(String, index=True)
    download_link = Column(String,index=True)

    file = relationship("File",back_populates="downloaded_song")
    song_submit = relationship("SongSubmit", back_populates="downloaded_song")
