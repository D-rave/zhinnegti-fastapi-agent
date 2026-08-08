"""管理后台 API（知识库管理完整版）"""
import os
import shutil
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.user import User
from api.deps import get_current_user
from utils.logger_handler import logger
from schemas.common import ResponseBase

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """仪表盘统计数据"""
    return {
        "success": True,
        "data": {
            "total_users": 0,
            "total_sessions": 0,
            "total_messages": 0,
            "knowledge_files": len(os.listdir(UPLOAD_DIR)) if os.path.exists(UPLOAD_DIR) else 0
        }
    }


@router.post("/knowledge/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    上传知识库文件并自动向量化
    支持: pdf, txt, docx, md
    """
    allowed_extensions = {".pdf", ".txt", ".docx", ".md"}
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}，仅支持: {', '.join(allowed_extensions)}"
        )

    # 安全检查
    safe_filename = os.path.basename(file.filename)
    if ".." in safe_filename or "/" in safe_filename or "\\" in safe_filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    # 如果文件已存在，先删旧向量（避免重复）
    if os.path.exists(file_path):
        try:
            _delete_vector_by_source(file_path)
        except Exception as e:
            logger.warning(f"删除旧向量失败（可能不存在）: {e}")

    try:
        # 1. 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. 读取内容
        content = _read_file_content(file_path, ext)
        if not content or len(content.strip()) == 0:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail="文件内容为空")

        # 3. 分割文本
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )
        chunks = splitter.split_text(content)

        # 4. 构建 Document 列表
        documents = [
            Document(
                page_content=chunk,
                metadata={"source": file_path, "filename": safe_filename, "chunk_index": i}
            )
            for i, chunk in enumerate(chunks)
        ]

        # 5. 存入向量库（如果 DashScope 欠费，这里会报错）
        _add_documents_to_vectorstore(documents)

        logger.info(f"知识库上传成功: {safe_filename}, 共 {len(chunks)} 个片段")

        return {
            "success": True,
            "message": "上传成功",
            "data": {
                "filename": safe_filename,
                "chunks": len(chunks),
                "size": os.path.getsize(file_path)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error(f"知识库上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.get("/knowledge/list")
async def list_knowledge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取已上传的知识库文件列表"""
    files = []
    if not os.path.exists(UPLOAD_DIR):
        return {"success": True, "data": []}

    for filename in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.isfile(file_path):
            stat = os.stat(file_path)
            files.append({
                "id": filename,
                "filename": filename,
                "size": stat.st_size,
                "uploaded_at": stat.st_mtime,
                "path": file_path
            })

    files.sort(key=lambda x: x["uploaded_at"], reverse=True)
    return {"success": True, "data": files}


@router.delete("/knowledge/{filename}")
async def delete_knowledge(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除知识库文件（同时清向量库）"""
    safe_filename = os.path.basename(filename)
    if ".." in safe_filename or "/" in safe_filename or "\\" in safe_filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        # 1. 清向量库
        _delete_vector_by_source(file_path)

        # 2. 删物理文件
        os.remove(file_path)

        return {"success": True, "message": "删除成功"}
    except Exception as e:
        logger.error(f"删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ========== 辅助函数（向量库操作）==========

def _read_file_content(file_path: str, ext: str) -> str:
    """读取不同格式文件"""
    if ext in (".txt", ".md"):
        encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ValueError("无法解码文本文件")

    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            return "".join([page.extract_text() or "" for page in reader.pages])
        except ImportError:
            raise HTTPException(status_code=500, detail="缺少 pypdf，请执行: pip install pypdf")

    elif ext == ".docx":
        try:
            from docx import Document
            doc = Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs])
        except ImportError:
            raise HTTPException(status_code=500, detail="缺少 python-docx，请执行: pip install python-docx")

    else:
        raise ValueError(f"不支持的格式: {ext}")


def _add_documents_to_vectorstore(documents: list):
    """添加文档到向量库（封装，方便异常处理）"""
    try:
        from rag.vector_store import VectorStoreService
        vs = VectorStoreService()
        if hasattr(vs, 'vectorstore') and vs.vectorstore:
            vs.vectorstore.add_documents(documents)
            # 持久化
            if hasattr(vs.vectorstore, '_persist'):
                vs.vectorstore._persist()
        else:
            raise RuntimeError("向量库未初始化")
    except Exception as e:
        logger.error(f"向量库写入失败: {e}")
        raise


def _delete_vector_by_source(file_path: str):
    """按 source 元数据删除向量"""
    try:
        from rag.vector_store import VectorStoreService
        vs = VectorStoreService()
        if hasattr(vs, 'vectorstore') and hasattr(vs.vectorstore, '_collection'):
            vs.vectorstore._collection.delete(where={"source": file_path})
    except Exception as e:
        logger.warning(f"向量删除失败（可能不存在）: {e}")