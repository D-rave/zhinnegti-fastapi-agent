"""
安全增强工具 - 生产级输入净化与敏感数据处理
"""
import re
import html
import hashlib
import hmac
import base64
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from core.config import get_settings

settings = get_settings()


# ========== 1. XSS 防护 ==========

def sanitize_html(text: str) -> str:
    """净化用户输入，转义 HTML 特殊字符"""
    if not text:
        return ""
    text = html.escape(text)
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'data:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'vbscript:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bon\w+\s*=', '', text, flags=re.IGNORECASE)
    return text


# ========== 【新增】日志净化兼容函数 ==========

def sanitize_for_log(text: str, max_length: int = 500) -> str:
    """
    净化日志内容，防止日志注入
    兼容旧代码调用
    """
    if not text:
        return ""
    text = text[:max_length]
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\t')
    return text


# ========== 2. 生产级输入净化器 ==========

class InputSanitizer:
    """
    统一输入净化器
    用于：聊天输入、搜索关键词、文件元数据等所有用户可控输入
    """

    SQL_BLACKLIST = [
        "drop", "delete", "truncate", "alter", "exec", "execute",
        "union", "insert", "update", "grant", "revoke", "--", "/*", "*/",
        "xp_", "sp_", "sysobjects", "syscolumns"
    ]

    CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')
    ZERO_WIDTH_CHARS = re.compile(r'[\u200b\u200c\u200d\ufeff\u2060\ufeff]')

    PHONE_PATTERN = re.compile(r'1[3-9]\d{9}')
    ID_CARD_PATTERN = re.compile(r'\d{17}[\dXx]|\d{15}')
    EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    @classmethod
    def sanitize(cls, text: str, max_length: int = 2000, context: str = "chat") -> str:
        """统一净化入口"""
        if not text or not isinstance(text, str):
            return ""

        text = cls.ZERO_WIDTH_CHARS.sub('', text)
        text = cls.CONTROL_CHARS.sub('', text)

        if len(text) > max_length:
            text = text[:max_length]

        if context == "chat":
            text = cls._sanitize_chat(text)
        elif context == "search":
            text = cls._sanitize_search(text)
        elif context == "filename":
            text = cls._sanitize_filename(text)

        text = text.strip()
        return text

    @classmethod
    def _sanitize_chat(cls, text: str) -> str:
        """聊天消息专用净化"""
        text = sanitize_html(text)

        for keyword in cls.SQL_BLACKLIST:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            text = pattern.sub('[filtered]', text)

        text = re.sub(r'\n{5,}', '\n\n\n', text)
        return text

    @classmethod
    def _sanitize_search(cls, text: str) -> str:
        """搜索关键词专用净化"""
        text = re.sub(r'[<>\"\'`;]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @classmethod
    def _sanitize_filename(cls, text: str) -> str:
        """文件名专用净化"""
        import os
        text = re.sub(r'[\\/*?:"<>|]', '', text)
        text = re.sub(r'\.{2,}', '', text)
        if len(text) > 100:
            name, ext = os.path.splitext(text)
            text = name[:100] + ext
        return text.strip()

    @classmethod
    def mask_sensitive_for_log(cls, text: str) -> str:
        """日志脱敏：手机号、身份证号、邮箱"""
        if not text:
            return ""
        text = cls.PHONE_PATTERN.sub(lambda m: m.group(0)[:3] + '****' + m.group(0)[-4:], text)
        text = cls.ID_CARD_PATTERN.sub(lambda m: m.group(0)[:4] + '**********' + m.group(0)[-4:], text)
        text = cls.EMAIL_PATTERN.sub(lambda m: m.group(0).split('@')[0][:2] + '***@' + m.group(0).split('@')[1], text)
        return text


# ========== 3. 敏感数据加密 ==========

def _get_fernet() -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'zhinengti_salt_v1',
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.SECRET_KEY.encode()))
    return Fernet(key)


def encrypt_sensitive(data: str) -> str:
    if not data:
        return ""
    f = _get_fernet()
    return f.encrypt(data.encode()).decode()


def decrypt_sensitive(token: str) -> str:
    if not token:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(token.encode()).decode()
    except Exception:
        return ""


# ========== 4. API 密钥管理 ==========

class APIKeyManager:
    def __init__(self):
        self._keys: dict[str, str] = {}
        self._key_versions: dict[str, int] = {}

    def hash_key(self, raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def verify_key(self, raw_key: str, hashed_key: str) -> bool:
        return hmac.compare_digest(self.hash_key(raw_key), hashed_key)

    def rotate_key(self, name: str, new_key: str):
        self._keys[name] = self.hash_key(new_key)
        self._key_versions[name] = self._key_versions.get(name, 0) + 1
        return {
            "name": name,
            "version": self._key_versions[name],
            "hashed": self._keys[name][:16] + "..."
        }

    def get_key_info(self, name: str) -> dict:
        return {
            "name": name,
            "version": self._key_versions.get(name, 0),
            "exists": name in self._keys,
        }


api_key_manager = APIKeyManager()