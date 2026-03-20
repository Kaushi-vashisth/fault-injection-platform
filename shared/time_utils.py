import time

def timestamp_iso() -> str:
    t = time.time()
    return time.strftime('%Y-%m-%dT%H:%M:%S.', time.gmtime(t)) + \
           f"{int((t % 1) * 1000000):06d}Z"

def get_timestamp() -> float:
    return time.time()