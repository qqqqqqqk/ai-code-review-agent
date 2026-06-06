"""
AI Code Review Agent
====================
监听 GitHub Webhook → 拉取代码 → Claude 分析 → 回复 PR 评论
"""

import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request, HTTPException
from config import GITHUB_TOKEN, DEEPSEEK_API_KEY, WEBHOOK_SECRET

app = FastAPI(title="AI Code Review Agent")

# ─────────────────────────────────────────
# 1. 接收 GitHub Webhook
# ─────────────────────────────────────────
@app.post("/webhook")
async def handle_webhook(request: Request):
    """GitHub 有 PR 事件时，会 POST 到这里"""

    # 验证请求确实来自 GitHub（安全校验）
    body = await request.body()
    verify_github_signature(body, request.headers.get("X-Hub-Signature-256", ""))

    data = await request.json()
    event = request.headers.get("X-GitHub-Event")

    # 只处理 PR 被打开 或 有新提交 的事件
    if event == "pull_request" and data.get("action") in ["opened", "synchronize"]:
        pr_number = data["pull_request"]["number"]
        repo      = data["repository"]["full_name"]
        pr_title  = data["pull_request"]["title"]

        print(f"[收到事件] PR #{pr_number}: {pr_title} ({repo})")

        # 异步处理，不让 GitHub 等太久
        await process_pull_request(repo, pr_number)

    return {"status": "ok"}


# ─────────────────────────────────────────
# 2. 拉取 PR 改动的代码
# ─────────────────────────────────────────
async def process_pull_request(repo: str, pr_number: int):
    """完整流程：拉代码 → AI分析 → 回复评论"""

    print(f"[开始分析] {repo} PR #{pr_number}")

    # 2.1 通过 GitHub API 拿到改动的文件列表
    files = await get_pr_files(repo, pr_number)
    if not files:
        print("[跳过] 没有文件改动")
        return

    # 2.2 把改动内容整理成文本，喂给 AI
    code_diff = format_code_diff(files)

    # 2.3 调用 DeepSeek 做 Code Review
    review = await ask_deepseek_for_review(code_diff)

    # 2.4 把 AI 的意见，以评论形式回复到 PR
    await post_pr_comment(repo, pr_number, review)
    print(f"[完成] PR #{pr_number} Code Review 已发布")


async def get_pr_files(repo: str, pr_number: int) -> list:
    """调用 GitHub API，获取 PR 改动的文件"""
    url     = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def format_code_diff(files: list) -> str:
    """把多个文件的改动，拼成一段文字给 AI 看"""
    result = []
    for f in files[:10]:  # 最多分析10个文件，避免超出token限制
        filename = f["filename"]
        patch    = f.get("patch", "（二进制文件或内容过大，已跳过）")
        result.append(f"### 文件：{filename}\n```diff\n{patch}\n```")

    return "\n\n".join(result)


# ─────────────────────────────────────────
# 3. 调用 DeepSeek API 做 Code Review
# ─────────────────────────────────────────
async def ask_deepseek_for_review(code_diff: str) -> str:
    """把代码改动发给 DeepSeek，返回 Review 意见"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "user",
                "content": f"""你是一位资深工程师，正在做 Code Review。
请分析以下代码改动，给出简洁、有价值的反馈。

重点关注：
1. **潜在 Bug**：空指针、边界条件、异常处理
2. **安全问题**：SQL注入、XSS、敏感信息泄露
3. **代码质量**：可读性、命名规范、重复代码
4. **性能问题**：不必要的循环、数据库N+1查询

格式要求：
- 用中文回复
- 每个问题标注 🔴严重 / 🟡建议 / 🟢优化
- 如果代码没问题，就说"✅ 代码质量良好"
- 控制在300字以内

---
代码改动如下：

{code_diff}
"""
            }
        ],
        "max_tokens": 1024
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ─────────────────────────────────────────
# 4. 把 AI 意见回复到 GitHub PR
# ─────────────────────────────────────────
async def post_pr_comment(repo: str, pr_number: int, comment: str):
    """通过 GitHub API，在 PR 下面发一条评论"""
    url     = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    body = {
        "body": f"## 🤖 AI Code Review\n\n{comment}\n\n---\n*由 AI Agent 自动生成*"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()


# ─────────────────────────────────────────
# 5. 安全校验：确认请求来自 GitHub
# ─────────────────────────────────────────
def verify_github_signature(body: bytes, signature: str):
    """用 HMAC 验证 Webhook 请求确实来自 GitHub，防止伪造"""
    if not WEBHOOK_SECRET:
        return  # 开发环境可以跳过

    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="签名验证失败")


# ─────────────────────────────────────────
# 6. 健康检查接口（UptimeRobot 监控用）
# ─────────────────────────────────────────
@app.get("/health")
def health_check():
    """UptimeRobot 每5分钟请求这个接口，确认服务还活着"""
    return {"status": "alive", "service": "AI Code Review Agent"}
