# 每日 AI 新闻助手 Agent

本机单用户 MVP：Vue 3 + FastAPI + MySQL + LangGraph。LLM 使用注册工具自主获取 RSS 材料、按偏好生成中文简报；简报保存后通过已验证的本人邮箱投递。

## 5 分钟快速启动

适用于已安装 Git、Node.js 22.12+/24 LTS 和 uv、且网络可用的 Windows 电脑，通常可在 5 分钟内启动。首次下载依赖的耗时取决于网速；快速体验使用独立 SQLite 数据库，不需要安装 MySQL、填写模型密钥或配置 SMTP。

```powershell
git clone https://github.com/dafuhao111/daily-ai-news-assistant.git
cd daily-ai-news-assistant
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quickstart.ps1
```

看到 `http://127.0.0.1:8000/` 后打开浏览器即可。脚本自动安装锁定依赖、构建前端、执行 SQLite migration、仅在新数据库初始化预算并启动服务；它使用 `backend/data/quickstart.db`，保留已有 `.env` 和数据库。快速模式关闭定时任务，不发送邮件。若要生成真实 AI 简报，在 `backend/.env` 配置自己的 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。完整 MySQL 安装见 [backend/README.md](backend/README.md)。

## MySQL 本地运行

需要 Node.js 22.12+/24 LTS、uv 和 MySQL。先在 `backend/.env` 配置数据库连接，再运行安装脚本；脚本不会覆盖已有配置。

在项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PrepareOnly
# 首次准备后，编辑 backend/.env 并创建 MySQL 数据库和低权限账号，再继续：
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

MySQL 配置、预算初始化、邮件和调度说明见 [backend/README.md](backend/README.md)。当前应用只面向本机单用户，不开放公网访问。

## 项目文档

- [产品设计文档](docs/产品设计文档.md)
- [技术方案](docs/技术方案.md)

2026-11-22：后端完整测试 139 通过、1 项 Windows 符号链接权限跳过；前端 40 项通过；已保存真实简报并向已验证目标提交 1 次新闻邮件，用户明确确认收到该封包含 4 条新闻的简报。SMTP 记录仍为 submitted，收件证据来自本人确认，不代表已配置自动送达回执。每日订阅及调度当前停用，验收不会自动开启长期推送。
