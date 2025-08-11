from threading import Lock
from collections import defaultdict


jobs = {}
key_locks = defaultdict(Lock)

def safe_write(key, value):
    lock = key_locks[key]
    with lock:
        jobs[key] = value

def safe_read(key):
    lock = key_locks[key]
    with lock:
        return jobs.get(key)