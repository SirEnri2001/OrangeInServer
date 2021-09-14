import asyncio
import json
import os
import threading
import urllib.request
import traceback
import random
import requests
import selenium.common.exceptions
import sqlalchemy.orm
from urllib.error import HTTPError
from selenium import webdriver
from music_dl.addons import netease

from database import crud
from database import schemas
from database import models
from util import audio
from selenium.webdriver.chrome.options import Options

user_agent_list = ["Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
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
    'goog:loggingPrefs': {'performance': 'ALL'},   # 记录性能日志
    'goog:chromeOptions': {'extensions': [], 'args': ['--headless',
                                                      '--no-sandbox',
                                                      '--disable-dev-shm-usage',
                                                      'blink-settings=imagesEnabled=false',
                                                      '--disable-gpu',
                                                      'Connection=close']}  # 无界面模式
}


def get_song_key(shared_link: str):
    user_agent = random.choice(user_agent_list)
    caps['goog:chromeOptions']['args'].append('User-Agent='+user_agent)
    # 根据用户提交的分享链接类型判断QQ还是网易云音乐
    if shared_link.find("y.music.163.com") != -1:
        return _get_song_key_netease(shared_link)
    elif shared_link.find("y.qq.com") != -1:
        return _get_song_key_qq(shared_link)


def get_song_info(shared_link: str,db:sqlalchemy.orm.Session, call_back: bool = False):
    print("Get song shared link: "+shared_link)
    try:
        # 根据用户提交的分享链接类型判断QQ还是网易云音乐
        if shared_link.find("music.163.com") != -1:
            song_info = _get_song_info_netease(shared_link)
        elif shared_link.find("y.qq.com") != -1:
            song_info = _get_song_info_qq(shared_link)
        else:
            return None
    except selenium.common.exceptions.WebDriverException as e:
        traceback.print_exc()
        raise SystemError("Server has no internet connection")
    if call_back:
        print("callback")
        crud.get_song_info_callback(db, song_info)
    else:
        return song_info


def _get_song_key_qq(shared_link: str):
    # 初始化webdriver
    driver = webdriver.Chrome(desired_capabilities=caps)
    # 通过分享链接获取mid
    driver.get(shared_link)
    logs = driver.get_log("performance")
    log = json.loads(logs[-1]["message"])["message"]
    if log['method'] == 'Page.frameNavigated':
        frag = log['params']['frame']['urlFragment']
        ind = frag.find("mid=")
        mid = frag[ind + 4:ind + 18]
    else:
        driver.quit()
        return None
    driver.quit()
    return mid


def _get_song_key_netease(shared_link: str):
    return shared_link[shared_link.find("id=")+3:shared_link.find("&uct=")]


def _get_song_info_qq(shared_link: str):
    if not shared_link.find("/songDetail/") == -1:
        mid = shared_link[shared_link.find("songDetail/")+11:len(shared_link)]
    else:
        # 通过分享链接获取mid
        print("requests get: "+shared_link)
        res = requests.get(shared_link)
        mid = res.text.split('mid&#61;')[1].split('&#38;')[0]
    print(mid)
    if mid is None:
        return
    # 获取歌曲标题、歌手、专辑封面等信息
    print("requests get: "+'songDetail/'+mid)
    res = requests.get("https://y.qq.com/n/ryqq/songDetail/"+mid)
    _res_list = res.text.split('window.__INITIAL_DATA__ ={"detail":{')[1].split("}")[0].split('"title":"')
    title = _res_list[1].split('"')[0]
    artist = _res_list[2].split('"')[0]
    pic_link = "http://y.qq.com"+res.text.split("window.__INITIAL_DATA__ ={")[1].split("?max_age=")[0].split('y.qq.com')[1].encode('utf-8').decode("unicode_escape")
    song_title = title
    song_artist = artist
    # 获取QQ音乐文件本地下载链接
    res = requests.get("https://u.y.qq.com/cgi-bin/musicu.fcg?format=json&data=%7B%22req_0%22:%7B%22"
                       "module%22:%22vkey.GetVkeyServer%22,%22method%22:%22CgiGetVkey%22,%22param%22:%7B%22"
                       "guid%22:%22358840384%22,%22songmid%22:%5B%22"
                       + mid +
                       "%22%5D,%22songtype%22:%5B0%5D,%22uin%22:%221443481947%22,%22"
                       "loginflag%22:1,%22platform%22:%2220%22%7D%7D,%22comm%22:%7B%22uin%22:%2218585073516%22,%22"
                       "format%22:%22json%22,%22ct%22:24,%22cv%22:0%7D%7D")
    json_res = json.loads(res.text)
    print("https://isure.stream.qqmusic.qq.com/" +
                                  json_res['req_0']['data']['midurlinfo'][0]['purl'])
    return models.DownloadedSong(
                    filename="Content Not Local",
                    key=mid,
                    picture_link=pic_link,
                    title=song_title,
                    artist=song_artist,
                    shared_link=shared_link,
                    download_link="https://isure.stream.qqmusic.qq.com/" +
                                  json_res['req_0']['data']['midurlinfo'][0]['purl']
                )


def _get_song_info_netease(shared_link:str):
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
    return models.DownloadedSong(
                    filename="Content Not Local",
                    key=md_info.id,
                    picture_link=md_info.cover_url,
                    title=md_info.title,
                    artist=md_info.singer,
                    shared_link=shared_link,
                    download_link=md_info.song_url
                )


def __get_song_info_netease(shared_link: str):
    global res
    # 初始化webdriver
    driver = webdriver.Chrome(desired_capabilities=caps)
    # 外链播放器地址及获取
    print(shared_link[shared_link.find("id=")+3:len(shared_link)])
    if shared_link.find("&uct")!=-1:
        _url = 'https://music.163.com/outchain/player?type=2&id=' + \
               shared_link[shared_link.find("id=") + 3:shared_link.find("&uct=")] \
               + '&auto=1&height=66'
    else:
        _url = 'https://music.163.com/outchain/player?type=2&id='+ \
                   shared_link[shared_link.find("id=")+3:len(shared_link)] \
                   +'&auto=1&height=66'
    print("Chrome core access to: "+_url)
    driver.get(_url)
    logs = driver.get_log("performance")
    # 获取音乐标题、歌手等信息
    title_html = driver.find_element_by_id('title')
    if title_html.get_attribute('textContent')=="":
        return
    title_text = title_html.get_attribute('textContent')
    pic_html = driver.find_element_by_id('cover').get_attribute('src')
    driver.quit()
    # 查看webdriver内Network中调试记录
    for item in logs:
        log = json.loads(item["message"])["message"]
        if log['method'] == 'Network.requestWillBeSent':
            params = log['params']
            # 找到音频文件下载链接（类型为Media）
            if params['type'] == 'Media':
                return models.DownloadedSong(
                    filename="Content Not Local",
                    key=shared_link[shared_link.find("id=")+3:shared_link.find("&uct=")],
                    picture_link=pic_html.split('?')[0],
                    title=title_text.split(" - ")[0],
                    artist=title_text.split(" - ")[1],
                    shared_link=shared_link,
                    download_link=params['request']['url'].__str__()
                )


def download_from_song_info(song_info: models.DownloadedSong):
    try:
        print("Retrieve song file from url: "+song_info.download_link)
        song_info.filename = song_info.download_link.split('/')[-1].split('?')[0]
        urllib.request.urlretrieve(
            song_info.download_link
            ,os.path.join(audio.file_path, song_info.filename))
    except urllib.error.HTTPError:
        raise ValueError("Need for retry")
    if song_info.filename.split(".")[-1].find("m4a") != -1:
        song_info.filename = audio.m4a_to_mp3(song_info.filename)
    return song_info


if __name__=="__main__":
    print(_get_song_info_qq("https://c.y.qq.com/base/fcgi-bin/u?__=RlFwKQ4y").download_link)
