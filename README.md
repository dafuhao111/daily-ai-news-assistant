# 每日 AI 新闻助手 Agent

本机单用户 MVP：Vue 3 + FastAPI + MySQL + LangGraph。LLM 使用注册工具自主获取 RSS 材料、按偏好生成中文简报；简报保存后通过已验证的本人邮箱投递。

## 从 GitHub 下载使用

每人独立安装、使用自己的数据库、模型 Key 和可选 SMTP，不连接作者服务器。首次使用请按 [GitHub 安装指南](docs/GitHub-install.md) 完成建库、环境配置和预算初始化。

Windows 在仓库根目录执行（第一步只准备示例配置，编辑配置后再执行安装）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PrepareOnly
# 按安装指南创建数据库并编辑 backend/.env，再继续：
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
# 全新数据库还需按指南一次性初始化自己的预算，然后启动：
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

脚本不覆盖已有配置，不自动初始化/重置预算。首次示例默认关闭调度；每日邮件需要另行验证邮箱、启用订阅并开启后端调度。当前没有公网鉴权，不用于多人共享网站。

## 本地运行

需要 Node.js 22.12/24、Python 3.12（项目最低 3.11）、uv 和 MySQL。已配置的本机环境可以直接使用现有 `backend/.env`，不要覆盖它。

在项目根目录构建前端：

```powershell
cd frontend
npm ci
npm run build
cd ../backend
uv sync --locked --extra dev
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

打开 <http://127.0.0.1:8000/>。首次安装的环境配置、每日任务启用、受控演示与备份步骤见 [部署与演示](docs/部署与演示.md)。

## 验收交付

2026-11-22 后续更新：[累计预算控制](docs/累计预算控制.md)已启用，整个项目共用 100 万输入加输出 Token，MySQL 持久化并发预留与实际用量；超时预留不自动退款。页面可查额度，重启不能清零。最新测试为后端 166 通过、1 权限跳过，前端 41 通过。

- [完整验收报告](docs/完整验收报告.md)：逐项结论、真实证据、安全措施及未验证事项。
- [部署与演示](docs/部署与演示.md)：环境变量、本地部署、测试命令和一次完整演示。
- [项目复盘](docs/项目复盘.md)：真实架构、工具循环、数据流、测试证据与实现边界。
- [面试讲解与问答](docs/面试讲解与问答.md)：2 分钟介绍、5 分钟讲解、10 个问答和 3 个技术亮点。
- [产品设计](docs/产品设计文档.md)、[技术方案](docs/技术方案.md)。

2026-11-22：后端完整测试 139 通过、1 项 Windows 符号链接权限跳过；前端 40 项通过；已保存真实简报并向已验证目标提交 1 次新闻邮件，用户明确确认收到该封包含 4 条新闻的简报。SMTP 记录仍为 submitted，收件证据来自本人确认，不代表已配置自动送达回执。每日订阅及调度当前停用，验收不会自动开启长期推送。
