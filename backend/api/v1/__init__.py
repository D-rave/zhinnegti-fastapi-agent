from fastapi import APIRouter

from . import auth, chat, users, admin, knowledge, system

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(chat.router, prefix="/chat", tags=["聊天"])
api_router.include_router(users.router, prefix="/users", tags=["用户"])
api_router.include_router(admin.router, prefix="/admin", tags=["管理后台"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["知识库"])
api_router.include_router(system.router, prefix="/system", tags=["系统配置"])