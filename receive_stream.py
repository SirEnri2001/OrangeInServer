import subprocess

if __name__ == "__main__":
    while True:
        subp = subprocess.Popen(args=['ffplay', '-nodisp', '-autoexit', 'rtmp://101.34.57.237/live/test'])
        subp.communicate()
