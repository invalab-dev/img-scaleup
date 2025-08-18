import redis, json, asyncio

r = redis.StrictRedis(host='localhost', port=6379, db=2, decode_responses=True)

# 5분(300초) 후 제거 → 파일 다운로드 기능 등 제한
# → 이미지 처리에 5분 이상 걸릴 경우, key가 삭제되어 progress 업데이트 등 오류 발생
# 따라서 ex=300 제거 
def redis_write(key, value):
    # value는 직렬화 가능한 dict
    r.set(key, json.dumps(value))

def redis_read(key):
    s = r.get(key)
    return json.loads(s) if s else None

async def redis_delete(key, ex=300):
    await asyncio.sleep(ex)
    r.delete(key)
