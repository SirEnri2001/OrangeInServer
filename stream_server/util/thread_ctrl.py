import threading

# clear(): start MuteSound thread
# set(): block MuteSound thread
block_silence = threading.Event()

# set(): start MuteSound thread
# clear(): block MuteSound thread
# wait_silence_thread.wait() when block_silence.set()
audio_thread_mutex = threading.Semaphore(value=1)
audio_entry_mutex = threading.Semaphore(value=1)
block_silence_mutex = threading.Semaphore(value=1)


arrangement_db_access = threading.Semaphore(value=1)
accept_song_submit_mutex = threading.Semaphore(value=1)
thread_concurrency_mutex = threading.Semaphore(value=1)
subp = None
