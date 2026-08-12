"""全局异常处理（增强版）"""
import traceback
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError
from jose import JWTError

from utils.logger_handler import logger
from core.config import get_settings
from core.security_enhanced import InputSanitizer

settings = get_settings()


class BusinessException(Exception):
    """业务异常"""
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(self.message)


def setup_exception_handlers(app: FastAPI):
    """注册全局异常处理器"""

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.code,
            content={"success": False, "message": exc.message, "data": None}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = []
        for error in exc.errors():
            field = ".".join(str(x) for x in error.get("loc", []))
            msg = error.get("msg", "参数错误")
            errors.append(f"{field}: {msg}")

        logger.warning(f"[Validation] 请求参数错误: {errors}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"success": False, "message": "请求参数错误", "data": {"errors": errors}}
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """处理 HTTP 异常（404、401 等）"""
        safe_detail = InputSanitizer.sanitize(str(exc.detail), max_length=200, context="log")
        safe_path = InputSanitizer.sanitize(str(request.url.path), max_length=200, context="log")

        logger.warning(f"[HTTP] {exc.status_code}: {safe_detail}, Path={safe_path}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": safe_detail
            }
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request: Request, exc: SQLAlchemyError):
        error_id = f"DB-{id(exc):x}"
        safe_path = InputSanitizer.sanitize(str(request.url.path), max_length=200, context="log")

        logger.error(
            f"[DBError] ID={error_id}, Path={safe_path}, "
            f"Error={type(exc).__name__}: {str(exc)}\n"
            f"{traceback.format_exc()}"
        )

        detail = f"数据库操作失败 (参考ID: {error_id})" if not settings.DEBUG else str(exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "message": detail, "error_id": error_id, "data": None}
        )

    @app.exception_handler(JWTError)
    async def jwt_exception_handler(request: Request, exc: JWTError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"success": False, "message": "认证失败，请重新登录", "data": None}
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理未捕获的全局异常"""
        error_id = f"ERR-{id(exc):x}"
        safe_path = InputSanitizer.sanitize(str(request.url.path), max_length=200, context="log")

        # 脱敏：防止异常信息中泄露手机号、身份证等
        error_msg = InputSanitizer.mask_sensitive_for_log(str(exc))

        logger.error(
            f"[GlobalError] ID={error_id}, Path={safe_path}, "
            f"Error={type(exc).__name__}: {error_msg}\n"
            f"{traceback.format_exc()}"
        )

        # 生产环境不暴露详细堆栈
        if settings.DEBUG:
            detail = str(exc)
        else:
            detail = f"服务器内部错误，请稍后重试 (参考ID: {error_id})"

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": detail,
                "error_id": error_id,
                "data": None
            }
        )