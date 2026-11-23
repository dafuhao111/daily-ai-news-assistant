# 从 GitHub 安装：每人独立运行

本指南面向下载仓库的新用户。每个人在自己的 Windows 电脑运行一套应用，使用自己的数据库、模型额度和可选发信邮箱。作者的本地 `.env`、邮箱授权码、历史简报和预算账本不会随仓库提供；不需要连接作者的服务器。

这不是公共共享网站部署。当前仍是本机单用户版本，没有网站登录、租户隔离或公网访问能力。不要通过绑定 `0.0.0.0`、开放端口或转发域名来提供共享服务。现有服务器不参与本次交付。

## 1. 准备软件和账号

安装 Git、Node.js **24 LTS**、uv 和 MySQL **8**，安装后重新打开 PowerShell。Python 由 uv 根据仓库 `backend/.python-version` 使用 **3.12**；首次同步可能自动下载，需要网络。

官方入口：[Git](https://git-scm.com/downloads)、[Node.js](https://nodejs.org/)、[uv](https://docs.astral.sh/uv/getting-started/installation/)、[MySQL](https://dev.mysql.com/downloads/installer/)。使用官方安装方式，不要求管理员运行本项目脚本；MySQL 服务的安装和管理可能需要管理员权限。

检查工具：

```powershell
git --version
node --version
npm.cmd --version
uv --version
```

还需要一个**支持工具调用且返回 usage 用量**的模型 API 账号及有效额度。模型调用会付费；只在本地填写 API Key。RSS 示例使用公开官方源，无额外搜索账号，但本机网络需要能访问这些网站。仅阅读和生成简报可以不配置 SMTP；每日邮件需要可用 SMTP 账号/授权码，限额以邮箱服务商规则为准。

## 2. 下载仓库并生成本地配置

在 GitHub 仓库页面点击 Code → 复制 HTTPS 地址，在想保存项目的目录执行以下模板。把 `YOUR_ACCOUNT/YOUR_REPO` 换为实际仓库地址，不能原样照抄占位符：

```powershell
git clone https://github.com/YOUR_ACCOUNT/YOUR_REPO.git daily-ai-news
cd daily-ai-news
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PrepareOnly
```

仓库也可由 IDEA 的 Get from Version Control 克隆。无论用哪个 IDE，项目根目录应包含 `backend`、`frontend`、`scripts` 和本 README。

`-PrepareOnly` 只在文件不存在时复制：

- `backend/.env.example` → `backend/.env`。
- `backend/config/rss_sources.example.json` → `backend/config/rss_sources.json`。

脚本不会覆盖现有文件，不安装依赖、不连接数据库、不初始化预算、不调用模型或发送邮件。首次不带参数运行 setup 时，如果刚创建 `.env`，也会停下来等待配置。`ExecutionPolicy Bypass` 只用于这次 PowerShell 子进程，不更改系统或当前用户的长期执行策略；企业策略禁止时请按组织规则处理。

## 3. 创建自己的 MySQL 数据库和账号

确认 MySQL 服务正在运行。在本机 Workbench 或 MySQL 客户端中，以管理员登录，执行以下 SQL，**先把密码占位符换为自己的独立强密码**。不要把真实 SQL 密码保存进仓库或发到聊天中。新安装可用至少 20 位随机字母数字密码，减少连接串转义错误。

```sql
CREATE DATABASE daily_ai_news CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'daily_ai_app'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_YOUR_OWN_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON daily_ai_news.* TO 'daily_ai_app'@'127.0.0.1';
```

这是仅限本项目库的权限，支持应用及表迁移，不授予全局权限或 GRANT OPTION。已有同名库/账号时先核对归属，不要删除重建或执行 DROP 来“修复”。不要在应用中使用 root。数据库管理员可能需要按实际 MySQL 本机认证配置调整账号 Host；下面连接使用 `127.0.0.1`。

用编辑器打开 `backend/.env`，配置数据库连接：

```dotenv
DATABASE_URL=mysql+pymysql://daily_ai_app:REPLACE_WITH_YOUR_OWN_STRONG_PASSWORD@127.0.0.1:3306/daily_ai_news?charset=utf8mb4
SCHEDULER_ENABLED=false
```

密码包含 `@`、`:`、`/`、`#`、`%` 等字符时，必须对密码部分做 URL 编码，不能对整条连接串编码。不要把含密码的 URL 贴到终端诊断、截图或 GitHub issue。项目不要求使用作者电脑的盘符或 MySQL 安装路径。

## 4. 配置自己的模型和 RSS

仍在 `backend/.env` 中配置：

```dotenv
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=REPLACE_WITH_YOUR_OWN_KEY
LLM_MODEL=REPLACE_WITH_PROVIDER_MODEL_ID
LLM_API_PROTOCOL=chat_completions
LLM_MAX_OUTPUT_TOKENS=2048
RSS_SOURCES_FILE=config/rss_sources.json
SCHEDULER_ENABLED=false
```

这段是格式模板，`api.example.com` 和占位符不能用于实际请求。支持 `chat_completions` 与 `responses`，应按供应商文档选协议和 Base URL。项目曾实测 HappyCode 的 `https://cn.happycodeapi.com` 根地址、`gpt-6.1-sol`、`responses`，该配置不加 `/v1`；这仅是历史兼容记录，不保证供应商未来可用、价格或所有模型行为。其他服务按自身要求配置，不能机械沿用根地址。

保留 RSS 示例即可开始。它包含 OpenAI、Google DeepMind、Microsoft Research 官方 feed，可能因网络、来源结构或超时出现部分失败。只配置可信 feed 和相应 `allowed_hosts`，不要为了兼容而关闭 SSRF/TLS 校验。实际配置文件已 Git 忽略，每人独立修改。

密钥只放后端 `.env`，不要使用 `frontend` 的 `VITE_*` 暴露秘密。默认资源限制、预算要求见[部署与演示](部署与演示.md)和[累计预算控制](累计预算控制.md)。

## 5. 安装、构建和迁移

回到仓库根目录，执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

脚本依次执行 `npm ci`、前端构建、`uv sync --locked`、Alembic `upgrade head`。命令失败立即停止，不继续迁移或假报成功；每条命令在对应项目目录中运行。已有数据库需要先备份，表迁移不是备份。脚本不自动创建数据库/用户、不安装 MySQL 服务，也不替你重置任何预算。

`npm.cmd` 用于避免 PowerShell 误选 `npm.ps1` 的执行策略问题；后端使用 `uv run --locked python -m ...`，不依赖另一个虚拟环境中的 uvicorn。首次网络下载需要时间，失败后修复原因再重跑，已有本地配置会保留。

## 6. 新数据库一次性初始化预算

**只有自己的全新数据库**需要执行一次：

```powershell
uv --directory .\backend run --locked python -m app.budget initialize --limit 1000000
uv --directory .\backend run --locked python -m app.budget status
```

这里的 100 万是本地累计输入加输出 Token 上限，可以在首次初始化时选择自己的合理额度；它不提供免费 Token，不是自动按月重置。全新项目默认历史用量为零，不复制作者的历史已用额度或安全预留。已有使用记录的迁移必须按自己的账单传入历史确认/待核对数值，不能当全新账本初始化。

重复初始化会被拒绝；更新项目、重启或额度用完时，**不要清表/删库来恢复额度**。未初始化会阻止模型调用，但不是模型 Key 错误。超时预留不会自动退回，核对方式见[预算说明](累计预算控制.md)。

## 7. 日常启动和首次验收

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

也可以从任意目录给 `-File` 传脚本绝对路径，脚本根据自身位置定位后端，不会再出现从用户主目录启动导致 `No module named app` 的问题。看到启动成功后打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。保持终端运行，Ctrl+C 停止；脚本不后台托管、不自动打开每日订阅。

首次按不发邮件路径检查：

1. 保存自己的称呼和可选角色；邮箱可稍后配置。
2. 保存话题、关键词和排除词，选择 `08:30` / `Asia/Shanghai`，**订阅保持关闭**。
3. 点击“立即运行”，这一步读取真实 RSS 并消耗自己模型账号额度。
4. 查看真实状态、来源链接和历史记录；无新闻、部分来源失败、预算不足与生成失败各有对应信息，不以条数固定为通过。
5. 再次点击会复用当天 completed/empty 任务，避免重复正常生成；不应看到虚构 Demo 新闻。

仅把 `SCHEDULER_ENABLED=false` 不能阻止已启用订阅的手动任务发信；要演示生成但不发信，订阅也必须关闭。

## 8. 可选：每日邮件

生成/历史功能可以不配置发信。需要推送时，在自己的 `.env` 填 SMTP，例如网易 163：

```dotenv
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_SECURITY=ssl
SMTP_USERNAME=your_name@163.com
SMTP_FROM_EMAIL=your_name@163.com
SMTP_PASSWORD=REPLACE_WITH_YOUR_OWN_SMTP_AUTHORIZATION_CODE
```

完整邮箱地址和授权码均由使用者提供，授权码不是邮箱登录密码。QQ/其他邮箱按其官方 SMTP 说明配置。服务商可能限速、限制日发送量或要求付费，不承诺邮箱适用于大规模发信。

修改配置后先重启。界面保存自己的收件邮箱 → 发送一封测试邮件 → 实际收到后确认 → 启用并保存订阅。最后将 `SCHEDULER_ENABLED=true` 并再次启动，检查页面“下次执行时间”。**开启后可能立即补做今天已经错过的任务并发送邮件。**

每日执行要求电脑开机、不休眠、联网，MySQL 和后端持续运行。关闭终端不会继续执行，当前没有开机启动服务。需要全天候运行时，应为个人实例另外规划服务托管；现有脚本不安装 Windows 任务计划程序。SMTP submitted 仅表示接受，unknown 不盲重发，失败不丢已保存简报。

## 9. 常见问题和更新

| 现象 | 处理 |
| --- | --- |
| `No module named app`，或 `--locked has no effect` | 使用 `scripts/start.ps1`，不要在用户主目录裸运行 uvicorn |
| 8000 端口占用 | 查看是否已有本项目运行；使用已有页面或在对应终端 Ctrl+C，别结束电脑上所有 Python 进程 |
| 页面 404 | 缺前端构建，完成 setup；不要直接使用未构建的仓库目录当静态站点 |
| 数据库连接/认证失败 | 检查 MySQL 服务、库、账号 Host、密码编码；不要把完整连接串发到 issue |
| `budget_not_initialized` | 确认这是全新库后执行一次预算初始化；已有库检查连接是否指错 |
| `budget_limit`/unknown 费用 | 查看只读 budget status，按账单核对，不自动清除预留 |
| 时间到了没有邮件 | 查订阅启用、邮箱验证、SCHEDULER_ENABLED、后端/MySQL 是否在运行，再查任务和投递状态 |
| 模型/RSS 网络失败 | 核对协议、供应商额度和本机外网连接，保留失败码；不要关闭安全校验或发送密钥 |

更新流程：备份数据库 → 在原终端停止后端和 Vite → 根目录 `git pull --ff-only` → 运行 setup → 运行 start。配置不会被脚本覆盖，预算保持原账本；先查看更新涉及的迁移说明。MySQL 备份与恢复必须单独验证，setup 不能替代恢复演练。

测试：setup 默认不安装测试依赖；开发者先执行 `uv --directory .\backend sync --locked --extra dev`，再在 backend 运行 `uv run --locked pytest -q`，在 frontend 运行 `npm.cmd test`。默认不会调用付费模型或真实邮件；真实服务测试需显式启用，参见[原部署说明](部署与演示.md)。

## 10. 作者通过 IDEA 发布仓库

当前本地已是 Git 仓库，**不要重新初始化或覆盖历史**。在 IDEA 打开包含 backend/frontend 的项目根目录，检查 Git 工具窗口变更列表后，使用 Git 菜单的 GitHub 分享/创建仓库入口；具体菜单名称随 IDEA 版本变化。按 IDE 的官方登录流程授权 GitHub，不把访问令牌放入本项目。

分享前核对：

- 只上传已检查的代码和示例，不勾选 `.env`、实际 RSS 配置、`backend/data/`、数据库备份、邮件截图、日志、`.venv`、`node_modules` 或构建产物。
- `.idea/`、`*.iml` 已忽略；原有未跟踪的分阶段提示词由作者自行决定是否分享，不自动加入本次提交。
- 检查 `git status --short`、待提交差异和历史；`.gitignore` 不会从过去提交中撤回已泄漏内容。已泄漏凭据要撤销/轮换后单独处理历史，不能仅删当前文件。本次不改写历史。
- 当前历史包含验收记录、运行 ID、本机路径及供应商信息；这些不是凭据，也不是需要分发的运行数据。作者应确认公开范围。新用户按本指南安装，不要复制作者 `.env`、数据库或诊断附件。
- 仓库可先设 Private，确认内容后再切 Public。未添加开源许可证时，公开可见不等于授予通用开源再分发许可；许可证类型由作者决定，本文不代选。

IDEA 创建远程后检查 `git remote -v`，确认目标正确再 Push；不要 force push。发布完成把实际仓库 URL 发给使用者，新用户在第 2 节替换模板地址即可。GitHub 只存代码，GitHub Pages 无法运行 Python、MySQL、定时 Agent 和 SMTP，本次不使用 Pages 作为后端。

## 11. 本次交付验证（2026-11-23）

- Windows PowerShell 5.1 与 PowerShell 7 的脚本测试共 **20 项通过**。在临时目录中运行实际脚本，以 CLI 替身验证首次只准备配置、重复不覆盖、锁定依赖参数、中文/空格路径、从其他工作目录启动、过旧 Node 拒绝、命令失败即停止、单 worker/本地绑定和启动失败上报。
- 后端默认全量测试 **178 passed、9 skipped**。跳过为 8 项未显式开启的真实模型/RSS/MySQL 测试，另 1 项 Windows 符号链接权限不足；没有删除或屏蔽失败。
- 前端 **41 项通过**，生产构建通过；新增 Python 测试的 Ruff 检查和格式检查通过，文档相对链接与 Git 差异检查通过。
- 另建立无个人配置的临时源码副本，真实执行 prepare、`npm ci/build`、全新虚拟环境的 `uv sync` 和 SQLite 迁移；新预算初始化为 100 万且历史用量为零。应用生命周期、静态页面、health/history/budget 和禁止访问 `.env` 检查通过。**这是 SQLite 安装冒烟验证，不是全新 MySQL 机器的完整实测，也没有调用真实模型或发信。**
- 比对当前本地已配置凭据及其连接串编码形式，扫描 291 个可达历史文件对象和新增交付文件，匹配为零。没有输出秘密；该检查不能证明所有未知历史凭据/个人信息都不存在，公开前仍需作者确认仓库内容。
- 本次没有创建远程仓库、Push、发布 Release、使用服务器或安装开机托管；按照作者选择，由 IDEA 创建/发布 GitHub 仓库。已有个人配置、数据库、预算和运行服务未由本次脚本修改。
