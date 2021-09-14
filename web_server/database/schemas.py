import datetime
from typing import List, Optional

from pydantic import BaseModel


class ItemBase(BaseModel):
    title: str
    description: Optional[str] = None


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    id: int
    owner_id: int

    class Config:
        orm_mode = True


class UserBase(BaseModel):
    email: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    is_active: bool
    items: List[Item] = []

    class Config:
        orm_mode = True


class UserInfoBase(BaseModel):
    username: str


class UserInfo(UserInfoBase):
    id: int

    class Config:
        orm_mode = True


class UserAuth(UserInfoBase):
    username: str
    password_checksum: str

    class Config:
        orm_mode = True


class UserInfoCreate(UserInfoBase):
    password_checksum: str


class FileBase(BaseModel):
    filename: str
    last_arranged: Optional[datetime.datetime]


class File(FileBase):
    checksum: str
    duration: str
    user_upload: int
    in_use: bool
    class Config:
        orm_mode = True


class FileCreate(FileBase):
    user_upload: int


class FilePlay(FileBase):
    pass


class ArrangementBase(BaseModel):
    begin_timestamp: datetime.datetime
    file: str
    is_valid: bool
    user_added: int
    title: str
    abstract: str


class Arrangement(ArrangementBase):
    end_timestamp: datetime.datetime
    audio_file: File
    class Config:
        orm_mode = True


class ArrangementCreate(ArrangementBase):
    pass


class SongSubmit(BaseModel):
    shared_link: str
    expDatetime: datetime.datetime
    email: str
    name: Optional[str]
    message: Optional[str]
    is_proceeded: Optional[bool]


class DownloadedSong(BaseModel):
    filename: str
    key: str
    picture_link: str
    title: str
    artist: str
    shared_link: str
    download_link: str

class DownloadedSongResponse(BaseModel):
    picture_link: str
    title: str
    artist: str


class RemotePlayCommand(BaseModel):
    url: str
    filename: str