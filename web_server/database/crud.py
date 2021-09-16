
import sqlalchemy.exc
from sqlalchemy.orm import Session




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
