"""单元测试共享配置：纯逻辑测试，不依赖 fastapi / 数据库 / 外部 API"""
import os
import sys

# 让测试可以直接 import backend 下的包（agent.middleware / utils 等）
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)