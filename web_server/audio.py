import asyncio
import os
import random
import re
import subprocess
import sys
import threading
import time
import uuid
import random
from subprocess import *

import requests
from ffmpy import FFprobe
import http.client, json
from xml.etree import ElementTree
from pydub import AudioSegment
import wave

from config import file_path, streaming_cmd
from thread_ctrl import *

subp = None


def get_audio_duration(filename):
    """
    Get duration of a certain file

    :param str filename: filename of absolute path.
    :return: audio play time duration in float
    """
    probe = FFprobe(global_options="-v quiet -print_format json -show_format",
                    inputs={os.path.join(file_path, filename): ""})
    res = probe.run(stdout=PIPE)
    if not res[1] is None:
        raise Exception(res[1])
    else:
        json_string = re.sub(r'[\r\n]', "", res[0].decode('utf-8'))
    info = json.loads(json_string)
    return float(info['format']['duration'])


def play_audio_blocked(filename):
    url = util.config.media_server
    res = requests.get(url + "/remote/find/" + filename)
    if res.status_code == 404:
        files = {'file': open(os.path.join(util.config.file_path,filename), 'rb')}
        try:
            r = requests.post(url=url+"/remote/upload", files=files).text
            if r is not None:
                requests.post(url+"/remote/play/"+filename)
        except Exception as e:
            print(e)
    else:
        requests.post(url+"/remote/play/"+filename)
    # AudioProcess(filename).run()


def play_audio_blocked_interval(filename):
    AudioProcess(filename).run_interval()


tlist = []


class AudioProcess:

    def __init__(self, filename):
        self.filename = filename

    def run(self):
        block_silence.set()
        print("Stand by for concurrency")
        thread_concurrency_mutex.acquire()
        audio_entry_mutex.acquire()
        thread_concurrency_mutex.release()
        audio_thread_mutex.acquire()
        print("block_silence set")
        audio_entry_mutex.release()
        if subp is not None:
            subp.kill()
        asubp = subprocess.Popen(args=streaming_cmd(self.filename))
        print("audio process created")
        tlist.append(asubp)
        asubp.communicate()
        print("audio process over")
        block_silence.clear()
        print("clear block_silence")
        tlist.remove(asubp)
        audio_thread_mutex.release()
        # subp = subprocess.Popen(args=["vlc","-vvv",self.filename,"--sout","'#standard{access=http,mux=mp3,dst=:8085/media}'","--http-host=0.0.0.0"])

    def run_interval(self):
        subp = subprocess.Popen(args=streaming_cmd(self.filename))
        tlist.append(subp)
        subp.communicate()
        tlist.remove(subp)
        # subp = subprocess.Popen(args=["vlc","-vvv",self.filename,"--sout","'#standard{access=http,mux=mp3,dst=:8085/media}'","--http-host=0.0.0.0"])

    @classmethod
    def stop_all(cls):
        for t in tlist:
            t.kill()


class MuteProcess:
    filename = "MuteSound.wav"
    subp = None

    @classmethod
    def set_mutefile(cls, filename):
        cls.filename = filename
        block_silence.clear()

    @classmethod
    def run(cls):
        global subp
        subp = None
        while True:
            thread_concurrency_mutex.acquire()
            audio_entry_mutex.acquire()
            thread_concurrency_mutex.release()
            print("mute_sound thread acquire")
            if not block_silence.is_set():
                if subp is None or subp.poll() is not None:
                    subp = subprocess.Popen(args=streaming_cmd(cls.filename))
                    print("start mutesound")
            else:
                if subp is not None and subp.poll() is None:
                    subp.kill()
                    print("stop mutesound")
                    # cls.subp.kill()
            time.sleep(0.2)
            audio_entry_mutex.release()


def create_speech(content):
    # Note: new unified SpeechService API key and issue token uri is per region
    # New unified SpeechService key
    # Free: https://azure.microsoft.com/en-us/try/cognitive-services/?api=speech-services
    # Paid: https://go.microsoft.com/fwlink/?LinkId=872236
    print(content)
    apiKey = "a775287d20614e92af25bd63e96d85dc"
    '''proxies = {
        "http": "http://127.0.0.1:10809",
        "https": "http://127.0.0.1:10809",
    }

    requests.get("http://example.org", proxies=proxies)'''

    params = ""
    headers = {"Ocp-Apim-Subscription-Key": apiKey}

    # AccessTokenUri = "https://westus.api.cognitive.microsoft.com/sts/v1.0/issueToken";
    AccessTokenHost = "eastasia.api.cognitive.microsoft.com"
    path = "/sts/v1.0/issueToken"

    # Connect to server to get the Access Token
    conn = http.client.HTTPSConnection(AccessTokenHost)
    conn.request("POST", path, params, headers)
    response = conn.getresponse()

    data = response.read()
    conn.close()

    accesstoken = data.decode("UTF-8")

    body = ElementTree.Element('speak', version='1.0')
    body.set('{http://www.w3.org/XML/1998/namespace}lang', 'zh-CN')
    voice = ElementTree.SubElement(body, 'voice')
    voice.set('{http://www.w3.org/XML/1998/namespace}lang', 'zh-CN')
    voice.set('{http://www.w3.org/XML/1998/namespace}gender', 'Male')
    voice.set('name', 'zh-CN-YunxiNeural')
    voice.text = content

    headers = {"Content-type": "application/ssml+xml",
               "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
               "Authorization": "Bearer " + accesstoken,
               "X-Search-AppId": "07D3234E49CE426DAA29772419F436CA",
               "X-Search-ClientID": "1ECFAE91408841A480F00935DC390960",
               "User-Agent": "TTSForPython"}

    # Connect to server to synthesize the wave
    print("\nConnect to server to synthesize the wave")
    conn = http.client.HTTPSConnection("eastasia.tts.speech.microsoft.com")
    conn.request("POST", "/cognitiveservices/v1", ElementTree.tostring(body), headers)
    response = conn.getresponse()

    data = response.read()
    conn.close()

    f = wave.open(os.path.join(file_path, "output.wav"), "wb")
    f.setnchannels(1)  # ?????????
    f.setframerate(24000)  # ?????????
    f.setsampwidth(2)  # sample width 2 bytes(16 bits)
    f.writeframes(data)
    f.close()
    return "output.wav"


def m4a_to_mp3(filename):
    """
    :param filename: which m4a being transferred
    :return: new mp3 filename
    """
    if filename.split('.')[-1].find("m4a") == -1:
        raise ValueError("Invalid filename")
    os.system("ffmpeg -i " + os.path.join(file_path, filename) + " " + os.path.join(file_path, filename.split('.')[
        0] + ".mp3") + " -y")
    return filename.split('.')[0] + ".mp3"


def joinVoice(file1_name, file2_name, saved_filename=None):
    # ?????????????????????????????????
    sound1 = AudioSegment.from_mp3(os.path.join(file_path, file1_name))
    sound2 = AudioSegment.from_mp3(os.path.join(file_path, file2_name))
    # ?????????????????????????????????
    db1 = sound1.dBFS
    db2 = sound2.dBFS
    dbplus = db1 - db2
    # ????????????
    if dbplus < 0:
        sound1 += abs(dbplus)
    else:
        sound2 += abs(dbplus)
    # ????????????????????????
    finSound = sound1 + sound2
    if saved_filename is None:
        save_name = "tmp_" + uuid.uuid4().hex + ".mp3"
    else:
        save_name = saved_filename
    print("save_path:", save_name)
    if os.path.exists(os.path.join(file_path, save_name)):
        os.remove(os.path.join(file_path, save_name))
    finSound.export(os.path.join(file_path, save_name), format="mp3")
    return save_name


def join_speech(speech, filename, saved_file_name=None):
    return joinVoice(create_speech(speech), filename, saved_file_name)


if __name__ == "__main__":
    print(sys.platform)
    # join_speech("???????????????????????????????????????????????????????????????????????????????????????",os.path.join(file_path,"11 Times Square (Full Mix).mp3"))
    # joinVoice("output.wav", "03 Mind The Gaps (Full Mix).mp3")
