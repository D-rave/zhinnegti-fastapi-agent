"""
长期记忆服务 V4
修复：
1. UserProfile 插入时补充 category 和 source_session 字段
2. 对话结束后自动提取摘要和关键事实
3. 同时保存到 SQLite（持久化）和 Chroma 向量库（语义检索）
4. 【修复】向量库操作改为异步，避免阻塞事件循环
"""
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.memory import ConversationSummary, UserProfile
from services.memory_vector_service import memory_vector_service
from model.factory import ChatModelFactory
from utils.logger_handler import logger


class MemoryService:
    """长期记忆服务：自动总结对话 + 双写存储（SQLite + 向量库）"""

    def __init__(self):
        self.llm = ChatModelFactory().generator()

    async def summarize_conversation(self, db: AsyncSession, session_id: str, user_id: int):
        """
        总结会话内容，提取关键信息
        同时写入 SQLite 和 Chroma 向量库
        """
        from models.chat import ChatMessage

        # 1. 获取会话消息
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        messages = result.scalars().all()

        if not messages:
            logger.info(f"[长期记忆] 会话 {session_id[:8]}... 无消息，跳过总结")
            return

        # 2. 构建对话文本
        dialog_text = "\n".join([
            f"{m.role}: {m.content}"
            for m in messages
        ])

        # 3. 调用 LLM 提取摘要和关键事实
        prompt = f"""请总结以下对话，提取关键信息：

{dialog_text}

请按以下 JSON 格式输出：
{{
    "summary": "对话摘要（50字以内）",
    "facts": ["关键事实1", "关键事实2", ...]
}}

只输出 JSON，不要其他内容。"""

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON
            json_str = content.strip()
            if json_str.startswith("```json"):
                json_str = json_str[7:]
            if json_str.startswith("```"):
                json_str = json_str[3:]
            if json_str.endswith("```"):
                json_str = json_str[:-3]
            json_str = json_str.strip()

            data = json.loads(json_str)
            summary_text = data.get("summary", "")
            facts = data.get("facts", [])

            # 4. 保存到 SQLite - ConversationSummary
            summary = ConversationSummary(
                session_id=session_id,
                user_id=user_id,
                summary=summary_text,
                key_facts=json.dumps(facts, ensure_ascii=False)
            )
            db.add(summary)

            # 5. 保存到 Chroma 向量库（【修复】改为异步）
            if summary_text:
                await memory_vector_service.save_summary_async(user_id, summary_text)

            # 6. 保存每个关键事实到 SQLite UserProfile 和 Chroma
            for fact in facts:
                if fact:
                    # Chroma 向量库（异步）
                    await memory_vector_service.save_fact_async(user_id, fact)

                    # SQLite UserProfile
                    profile = UserProfile(
                        user_id=user_id,
                        category="fact",
                        content=fact,
                        source_session=session_id
                    )
                    db.add(profile)

            await db.commit()
            logger.info(f"[长期记忆] 已保存会话 {session_id[:8]}... 的总结和 {len(facts)} 条画像")

        except Exception as e:
            logger.error(f"[长期记忆] 总结失败: {e}", exc_info=True)
            await db.rollback()