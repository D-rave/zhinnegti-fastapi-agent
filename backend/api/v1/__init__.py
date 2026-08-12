from api.v1 import admin as admin_api
from api.v1 import auth as auth_api
from api.v1 import chat as chat_api
from api.v1 import knowledge as knowledge_api
from api.v1 import system as system_api
from api.v1 import users as users_api
from api.v1 import usage as usage_api
from fastapi import APIRouter
from api.v1 import cost as cost_api
# ...

api_router = APIRouter()
api_router.include_router(cost_api.router, prefix="/cost", tags=["成本统计"])
api_router.include_router(auth_api.router, prefix="/auth", tags=["认证"])
api_router.include_router(chat_api.router, prefix="/chat", tags=["聊天"])
api_router.include_router(users_api.router, prefix="/users", tags=["用户"])
api_router.include_router(admin_api.router, prefix="/admin", tags=["管理后台"])
api_router.include_router(knowledge_api.router, prefix="/knowledge", tags=["知识库"])
api_router.include_router(system_api.router, prefix="/system", tags=["系统配置"])
api_router.include_router(usage_api.router, prefix="/usage", tags=["用量统计"])