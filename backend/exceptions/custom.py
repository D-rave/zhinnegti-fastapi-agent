"""自定义业务异常"""


class BusinessException(Exception):
    """通用业务异常"""
    def __init__(self, message: str = "业务错误", code: int = 400):
        self.message = message
        self.code = code
        super().__init__(self.message)


class NotFoundException(BusinessException):
    """资源不存在"""
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code=404)


class UnauthorizedException(BusinessException):
    """未授权"""
    def __init__(self, message: str = "未授权访问"):
        super().__init__(message=message, code=401)


class ForbiddenException(BusinessException):
    """禁止访问"""
    def __init__(self, message: str = "禁止访问"):
        super().__init__(message=message, code=403)


class ValidationException(BusinessException):
    """参数校验失败"""
    def __init__(self, message: str = "参数校验失败"):
        super().__init__(message=message, code=422)