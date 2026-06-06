"""
配置文件
========
把你的 Token 填到这里，或者用环境变量（推荐生产环境）
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# GitHub Personal Access Token
# 获取方式：GitHub → Settings → Developer settings → Personal access tokens
# 需要权限：repo（读写PR评论）
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# DeepSeek API Key
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# GitHub Webhook Secret（可选，建议生产环境填）
# 在 GitHub Webhook 配置页面填一个随机字符串，这里保持一致
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
