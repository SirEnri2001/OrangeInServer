import hashlib
import os
from .config import file_path


def get_md5_from_local_file(filename):
    """
    Get local file's MD5 Info.
    @param filename:file path & file name
    @return:MD5 Info
    """
    file_object = open(os.path.join(file_path,filename), 'rb')
    file_content = file_object.read()
    file_object.close()
    file_md5 = hashlib.md5(file_content)
    return file_md5.hexdigest()
