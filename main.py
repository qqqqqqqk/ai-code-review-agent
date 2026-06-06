"""
AI Code Review Agent
====================
监听 GitHub Webhook → 拉取代码 → Claude 分析 → 回复 PR 评论
"""

import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from config import GITHUB_TOKEN, DEEPSEEK_API_KEY, WEBHOOK_SECRET

app = FastAPI(title="AI Code Review Agent")

# ─────────────────────────────────────────
# 1. 接收 GitHub Webhook
# ─────────────────────────────────────────
@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks): # 2. 注入参数
    """GitHub 有 PR 事件时，会 POST 到这里"""

    body = await request.body()
    verify_github_signature(body, request.headers.get("X-Hub-Signature-256", ""))

    data = await request.json()
    event = request.headers.get("X-GitHub-Event")
    action = data.get("action")
    print(f"[收到 Webhook 原始请求] Event: {event}, Action: {action}")

    # 只处理 PR 被打开 或 有新提交 的事件
    if event == "pull_request" and action in ["opened", "synchronize"]:
        pr_number = data["pull_request"]["number"]
        repo      = data["repository"]["full_name"]
        pr_title  = data["pull_request"]["title"]

        print(f"[收到事件] PR #{pr_number}: {pr_title} ({repo})")

        # ❌ 删掉这行旧的：await process_pull_request(repo, pr_number)
        
        #  改成真正的后台任务！秒回 GitHub，不让对方死等
        background_tasks.add_task(process_pull_request, repo, pr_number)
        print(f"[后台任务已挂载] PR #{pr_number} 已移交后台异步处理")

    return {"status": "ok"}


# ─────────────────────────────────────────
# 2. 拉取 PR 改动的代码
# ─────────────────────────────────────────
async def process_pull_request(repo: str, pr_number: int):
    """完整流程：拉代码 → AI分析 → 回复评论"""
    try:
        print(f"[开始分析] {repo} PR #{pr_number}")

        files = await get_pr_files(repo, pr_number)
        if not files:
            print("[跳过] 没有文件改动")
            return

        code_diff = format_code_diff(files)
        print(f"[DEBUG] 成功获取 Diff 文本，长度: {len(code_diff)}，准备调用 DeepSeek...")

        review = await ask_deepseek_for_review(code_diff)
        print(f"[DEBUG] DeepSeek 成功返回 Review 内容！")

        await post_pr_comment(repo, pr_number, review)
        print(f"[完成] PR #{pr_number} Code Review 已发布")
        
    except Exception as e:
        # 如果后台报错了，这里一定会打印出堆栈！
        print(f"❌❌❌ [后台任务崩溃] 原因: {str(e)}")
        import traceback
        traceback.print_exc()

async def get_pr_files(repo: str, pr_number: int) -> list:
    """调用 GitHub API，获取 PR 改动的文件"""
    if not GITHUB_TOKEN:
        print("⚠️ [错误] 未配置 GITHUB_TOKEN，无法获取 PR 文件列表。请检查环境变量或 .env 文件。")
        return []

    url     = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "User-Agent": "AI-Code-Review-Agent",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        print(f"❌ [GitHub API 异常] 获取 PR 文件列表失败，状态码: {e.response.status_code}，详情: {e.response.text}")
    except Exception as e:
        print(f"❌ [请求异常] 获取 PR 文件列表时发生未知错误: {e}")
    return []


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
    if not DEEPSEEK_API_KEY:
        print("⚠️ [错误] 未配置 DEEPSEEK_API_KEY，无法调用 AI 服务。请检查环境变量或 .env 文件。")
        return "⚠️ 未配置 DEEPSEEK_API_KEY，无法调用 AI 服务进行审查。"

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

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        err_msg = f"DeepSeek API 请求失败，状态码: {e.response.status_code}"
        try:
            err_msg += f"，详情: {e.response.json().get('error', {}).get('message')}"
        except Exception:
            err_msg += f"，详情: {e.response.text}"
        print(f"❌ {err_msg}")
        return f"❌ AI 审查服务异常: {err_msg}"
    except Exception as e:
        print(f"❌ [DeepSeek 请求异常] 调用 DeepSeek 失败: {e}")
        return f"❌ 调用 DeepSeek 发生异常: {str(e)}"


# ─────────────────────────────────────────
# 4. 把 AI 意见回复到 GitHub PR
# ─────────────────────────────────────────
async def post_pr_comment(repo: str, pr_number: int, comment: str):
    """通过 GitHub API，在 PR 下面发一条评论"""
    if not GITHUB_TOKEN:
        print("⚠️ [错误] 未配置 GITHUB_TOKEN，无法发表 PR 评论。")
        return

    url     = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "User-Agent": "AI-Code-Review-Agent",
        "Accept": "application/vnd.github.v3+json"
    }
    body = {
        "body": f"## 🤖 AI Code Review\n\n{comment}\n\n---\n*由 AI Agent 自动生成*"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"❌ [GitHub API 异常] 发布 PR 评论失败，状态码: {e.response.status_code}，详情: {e.response.text}")
    except Exception as e:
        print(f"❌ [请求异常] 发布 PR 评论时发生未知错误: {e}")


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
