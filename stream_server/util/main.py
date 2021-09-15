import time

from stream_server.util.audio import *

if __name__=="__main__":
    test_mp3 = AudioProcess(filename="131.mp3")
    test_mp4 = AudioProcess(filename="120.mp3")
    t1 = threading.Thread(target=MuteProcess.run)
    t1.start()
    time.sleep(10)
    t2 = threading.Thread(target=test_mp3.run)
    t2.start()
    t3 = threading.Thread(target=test_mp4.run)
    t3.start()