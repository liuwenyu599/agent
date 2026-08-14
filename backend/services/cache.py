import time
class MemoryCache:
    def __init__(self): self._cache = {}; self._ttl = {}
    def get(self, key):
        if key in self._cache:
            if time.time() < self._ttl.get(key, 0): return self._cache[key]
            else: self.delete(key)
        return None
    def set(self, key, value, ttl=3600): self._cache[key] = value; self._ttl[key] = time.time() + ttl
    def delete(self, key): self._cache.pop(key, None); self._ttl.pop(key, None)
    def clear(self): self._cache.clear(); self._ttl.clear()
cache = MemoryCache()
