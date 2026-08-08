"""文件处理工具（安全增强版 + 兼容旧接口）"""
import os
import shutil
import hashlib
from pathlib import Path
from typing import Optional, List

from fastapi import UploadFile, HTTPException

# 兼容：如果 core.config 不存在（旧项目），使用默认值
try:
    from core.config import get_settings
    settings = get_settings()
    MAX_UPLOAD_SIZE = settings.MAX_UPLOAD_SIZE
    ALLOWED_EXTENSIONS = settings.allowed_extensions_list
except ImportError:
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = [".pdf", ".txt", ".docx", ".md"]


class FileHandler:
    """安全文件处理器"""

    @staticmethod
    def validate_file(file: UploadFile) -> None:
        """校验上传文件"""
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {ext}，仅支持: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        if ".." in file.filename or "/" in file.filename or "\\" in file.filename:
            raise HTTPException(status_code=400, detail="非法文件名")

    @staticmethod
    async def save_upload(file: UploadFile, destination_dir: str) -> str:
        """安全保存上传文件"""
        FileHandler.validate_file(file)
        os.makedirs(destination_dir, exist_ok=True)
        file_path = os.path.join(destination_dir, os.path.basename(file.filename))

        size = 0
        chunk_size = 1024 * 1024
        with open(file_path, "wb") as buffer:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件大小超过限制（最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）"
                    )
                buffer.write(chunk)
        return file_path

    @staticmethod
    def get_file_extension(filename: str) -> str:
        """获取文件扩展名"""
        return Path(filename).suffix.lower()

    @staticmethod
    def ensure_dir(directory: str) -> str:
        """确保目录存在"""
        os.makedirs(directory, exist_ok=True)
        return directory


# ==================== 兼容旧接口（rag/vector_store.py 等仍在使用）====================

def pdf_loader(file_path: str) -> str:
    """
    加载 PDF 文件内容
    兼容旧接口
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except ImportError:
        raise ImportError("请安装 pypdf: pip install pypdf")


def txt_loader(file_path: str) -> str:
    """
    加载 TXT 文件内容
    兼容旧接口
    """
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {file_path}")


def listdir_with_allowed_type(directory: str, allowed_extensions: Optional[List[str]] = None) -> List[str]:
    """
    列出目录中指定类型的文件
    兼容旧接口
    """
    if allowed_extensions is None:
        allowed_extensions = [".pdf", ".txt", ".docx", ".md"]

    if not os.path.exists(directory):
        return []

    files = []
    for filename in os.listdir(directory):
        ext = Path(filename).suffix.lower()
        if ext in allowed_extensions:
            files.append(os.path.join(directory, filename))
    return files


def get_file_md5_hex(file_path: str) -> str:
    """
    获取文件的 MD5 哈希值
    兼容旧接口
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()