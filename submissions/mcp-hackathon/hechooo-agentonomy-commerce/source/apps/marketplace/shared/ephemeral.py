from __future__ import annotations
import json
import threading
import time
from redis import Redis

class EphemeralStore:
    def __init__(self,url=None,*,clock=None):
        self.redis=Redis.from_url(url,decode_responses=True) if url else None
        self.memory={}
        self._lock=threading.Lock()
        self.clock=clock or time.monotonic
    def set(self,key,value,ttl=900):
        if self.redis:self.redis.setex(key,ttl,json.dumps(value,separators=(",",":")))
        else:self.memory[key]=(value,self.clock()+ttl)
    def get(self,key):
        if self.redis:
            value=self.redis.get(key)
            return json.loads(value) if value else None
        item=self.memory.get(key)
        if not item:return None
        value,expires_at=item
        if expires_at<=self.clock():
            self.memory.pop(key,None)
            return None
        return value
    def acquire(self,key,ttl=900):
        ttl=max(1,int(ttl))
        if self.redis:
            value=self.redis.getex(key,ex=ttl)
            return json.loads(value) if value else None
        value=self.get(key)
        if value is not None:self.memory[key]=(value,self.clock()+ttl)
        return value
    def delete(self,key):
        if self.redis:return bool(self.redis.delete(key))
        return self.memory.pop(key,None) is not None
    def pop(self,key):
        if self.redis:
            value=self.redis.getdel(key)
            return json.loads(value) if value else None
        with self._lock:
            item=self.memory.pop(key,None)
            if not item:return None
            value,expires_at=item
            return value if expires_at>self.clock() else None
