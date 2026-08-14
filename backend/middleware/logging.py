import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        ip = request.client.host if request.client else "unknown"
        response = await call_next(request)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {ip} {request.method} {request.url.path} - {response.status_code} - {time.time()-start:.3f}s")
        response.headers["X-Process-Time"] = str(time.time()-start)
        return response
