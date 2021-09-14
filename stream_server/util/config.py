import os

file_path = r"/home/Deployment/audio"

media_server = "101.34.57.237"


def streaming_cmd(filename):
    return _streaming_cmd_linux(filename)


def _streaming_cmd_linux(filename):
    return ["ffmpeg","-re","-i",os.path.join(file_path,filename),"-vcodec","null",'-ar','44100','-ab','128k','-ac','1',"-f","flv","-y","rtmp://0.0.0.0/live/test"]


def _streaming_cmd_win(filename):
    return ["ffplay","-autoexit","-nodisp","-i",os.path.join(file_path,filename)]
