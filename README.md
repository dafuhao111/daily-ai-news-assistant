# 每日 AI 新闻助手 Agent

本机单用户 MVP：Vue 3 + FastAPI + MySQL + LangGraph。LLM 使用注册工具自主获取 RSS 材料、按偏好生成中文简报；简报保存后通过已验证的本人邮箱投递。

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

- [完整验收报告](docs/完整验收报告.md)：逐项结论、真实证据、安全措施及未验证事项。
- [部署与演示](docs/部署与演示.md)：环境变量、本地部署、测试命令和一次完整演示。
- [产品设计](docs/产品设计文档.md)、[技术方案](docs/技术方案.md)。

2026-11-22：后端完整测试 139 通过、1 项 Windows 符号链接权限跳过；前端 40 项通过；已保存真实简报并向已验证目标提交 1 次新闻邮件。SMTP 接受不等于收件箱送达，实际收件仍待本人确认。每日订阅及调度当前停用，验收不会自动开启长期推送。
