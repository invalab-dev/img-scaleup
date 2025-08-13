import redis, json

r = redis.StrictRedis(host='localhost', port=6379, db=2, decode_responses=True)

# 5분(300초) 후 제거 → 파일 다운로드 기능 등 제한
def redis_write(key, value, ex=300):
    # value는 직렬화 가능한 dict
    r.set(key, json.dumps(value), ex=ex)

def redis_read(key):
    s = r.get(key)
    return json.loads(s) if s else None