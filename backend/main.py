from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from backend.api import auth, chat, knowledge, user, templates
from backend.middleware.logging import LoggingMiddleware
from backend.database.postgres import engine
from backend.database.models import Base

Base.metadata.create_all(bind=engine)

app = FastAPI(title="白云司法智能写作助手", description="基于大语言模型的司法公文智能写作系统", version="1.0.0")

app.add_middleware(LoggingMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1")
app.include_router(templates.router, prefix="/api/v1")

uploads_dir = "/home/lwy/judicial-ai/uploads"
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.on_event("startup")
async def startup_event():
    print("=" * 50)
    print("白云司法智能写作助手服务启动")
    print("API 文档: http://localhost:8000/docs")
    print("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    print("服务关闭")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
