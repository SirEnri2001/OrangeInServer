import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

from . import audio

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///jobs.sqlite')
}
executors = {
    'default': ThreadPoolExecutor(20),
    'processpool': ProcessPoolExecutor(5)
}
job_defaults = {
    'coalesce': False,
    'max_instances': 3
}
scheduler = BackgroundScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults)


class ArrangementScheduler:
    def __init__(self):
        if os.path.exists("jobs.sqlite"):
            os.remove("jobs.sqlite")
        self.scheduler = scheduler
        self.scheduler.remove_all_jobs("default")
        if not self.scheduler.state == 1:
            self.scheduler.start()
        print(self.scheduler.state)

    def add_job(self,filename,timestamp):
        print("filename:"+filename+" datetime:"+timestamp.__str__())
        self.scheduler.add_job(audio.play_audio_blocked,"date",
                               run_date=timestamp,args=[filename])


sche = ArrangementScheduler()
