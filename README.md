# 🤖 AI Code Review Agent

用 Claude AI 自动做 GitHub PR Code Review 的 Agent。

---

## 工作原理-

```
开发者提交 PR
     ↓
GitHub 发送 Webhook 通知到你的服务器
     ↓
Agent 调用 GitHub API 拉取代码改动
     ↓
Agent 把代码发给 Claude API 分析
     ↓
Agent 把分析结果回复到 PR 评论
     ↓
开发者看到 AI Review 意见 ✅
```

---

## 快速启动

### 第一步：安装依赖

```bash
pip install -r requirements.txt
```

### 第二步：填入配置

编辑 `config.py`，填入：
- `GITHUB_TOKEN`：去 GitHub → Settings → Developer settings → Personal access tokens 获取
- `ANTHROPIC_API_KEY`：去 https://console.anthropic.com 获取

或者用环境变量（推荐）：
```bash
export GITHUB_TOKEN="ghp_你的token"
export ANTHROPIC_API_KEY="sk-ant-你的key"
```

### 第三步：启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

启动后访问 http://localhost:8000/health 确认服务正常。

### 第四步：让外网能访问（本地开发用 ngrok）

```bash
# 安装 ngrok：https://ngrok.com/
ngrok http 8000

# 会得到一个公网地址，比如：
# https://abc123.ngrok.io
```

### 第五步：配置 GitHub Webhook

1. 打开你的 GitHub 仓库
2. Settings → Webhooks → Add webhook
3. 填写：
   - **Payload URL**：`https://abc123.ngrok.io/webhook`
   - **Content type**：`application/json`
   - **Events**：选 "Pull requests"
4. 点击 Add webhook

### 第六步：测试！

在仓库里提交一个 PR，等几秒钟，就会看到 AI 自动在 PR 下面评论了 🎉

---

## 部署到服务器（正式上线）

### 方式一：Docker（推荐）

```bash
# 构建镜像
docker build -t ai-code-review .

# 运行容器
docker run -d \
  -p 8000:8000 \
  -e GITHUB_TOKEN="你的token" \
  -e ANTHROPIC_API_KEY="你的key" \
  --name ai-review \
  --restart always \      # 崩了自动重启
  ai-code-review
```

### 方式二：Railway（最简单，免费起步）

1. 注册 https://railway.app
2. 新建项目，连接你的 GitHub 仓库
3. 在环境变量里填入 GITHUB_TOKEN 和 ANTHROPIC_API_KEY
4. 自动部署，Railway 给你一个公网地址

---

## 服务监控（保证 Agent 一直在线）

用 **UptimeRobot**（免费）监控：

1. 注册 https://uptimerobot.com
2. 添加监控：类型选 HTTP，填入你的地址 + `/health`
3. 每5分钟自动检测一次，挂了发邮件告警

---

## 文件说明

```
├── main.py          # 核心逻辑：Webhook接收、GitHub API、Claude API
├── config.py        # 配置：Token和Key
├── requirements.txt # Python依赖
├── Dockerfile       # Docker打包配置
└── README.md        # 本文档
```
