# 开发与 API 参考

[English](development.md) | 简体中文

## 仓库结构

- `app/server.py`：固定的正式入口，监听 `127.0.0.1:8000`。
- `app/demo_server.py`：固定的合成 Demo 入口，监听 `127.0.0.1:8001`。
- `app/backend/`：FastAPI 工厂、schema、迁移、store、路由与邮件实现。
- `app/frontend/`：React、TypeScript、Vite、Vitest 与 Playwright 配置。
- `app/tests/`：后端测试和公开的模拟招聘页面 fixture。
- `scripts/`：私有覆盖层初始化、环境自检、服务/Agent 封装、浏览器回归与发布检查。

明确的应用工厂用于分离运行权限：

- `create_app()` 是正式模式，不接受其他正式数据库。
- `create_test_app(paths)` 接受隔离测试显式传入的路径，保留邮件 API，并关闭调度；测试程序负责提供临时路径。
- `create_demo_app(paths)` 只接受经过校验的系统临时 Demo 会话，不构造邮件服务，也不挂载邮件和 Agent 路由。

简明运行说明见 [app/README.md](../app/README.md)。

## 安装与运行

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --locked --extra dev
pnpm --dir app\frontend install --frozen-lockfile
pnpm --dir app\frontend build
```

正式模式和 Demo 启动方式见[开始使用](getting-started.zh-CN.md)。开发用 Vite 监听 `127.0.0.1:5173`，并将 `/api` 代理到 8000 端口的正式服务。

## 健康接口与模式

`GET /api/health` 保留数据库和 schema 健康字段，并标识当前进程：

```json
{
  "status": "ok",
  "database": "available",
  "schema_version": 3,
  "service": "career-application-assistant",
  "mode": "standard",
  "synthetic_data": false,
  "mail_ingestion": true
}
```

测试模式返回 `mode: "test"`。Demo 返回 `mode: "demo"`、`synthetic_data: true` 和 `mail_ingestion: false`。启动与 Agent 脚本会检查这些身份字段，并始终拒绝 Demo。

## API 概览

所有接口都位于 `/api` 下并返回 JSON。POST 和 PATCH 请求必须使用 `Content-Type: application/json`，未定义字段会被拒绝。

| 方法 | 接口 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务身份、模式、数据库和迁移健康状态 |
| `GET` | `/api/applications` | 分页记录、筛选项与五列计数 |
| `POST` | `/api/applications` | 新建待复核记录 |
| `GET` | `/api/applications/{id}` | 记录详情与事件时间线 |
| `PATCH` | `/api/applications/{id}` | 编辑元数据、备注和下一步，不能直接改状态 |
| `DELETE` | `/api/applications/{id}` | 软删除记录 |
| `POST` | `/api/applications/{id}/events` | 追加经过校验的事件并在事务中更新状态 |
| `PATCH` | `/api/applications/{id}/events/{event_id}` | 修正事件详情并保留事件 ID |
| `POST` | `/api/agent/fill-completed` | 幂等记录已准备表单为待复核 |
| `POST` | `/api/agent/status-update` | 唯一匹配活动记录并追加结构化事件 |
| `GET` | `/api/mail/accounts` | 脱敏的服务商状态与待复核数量 |
| `POST` | `/api/mail/accounts/{provider}/connect` | 启动 Outlook 授权或校验并保存 IMAP 授权码 |
| `POST` | `/api/mail/accounts/{provider}/sync` | 启动一次有界增量读取 |
| `POST` | `/api/mail/accounts/{provider}/pause` | 暂停轮询并保留安全状态 |
| `POST` | `/api/mail/accounts/{provider}/resume` | 恢复轮询并请求同步 |
| `DELETE` | `/api/mail/accounts/{provider}` | 删除游标与安全凭据/令牌状态 |
| `GET` | `/api/mail/operations/{id}` | 查询脱敏的连接/同步操作 |
| `GET` | `/api/mail/candidates` | 返回不含原始邮件字段的结构化候选 |
| `POST` | `/api/mail/candidates/{id}/confirm` | 校验并追加人工确认的候选事件 |
| `POST` | `/api/mail/candidates/{id}/dismiss` | 忽略并清除候选字段 |
| `POST` | `/api/demo/reset` | 仅 Demo：使用空 JSON 请求体，在单一事务中恢复六条合成记录 |

Agent 匹配优先级为：活动记录 ID、规范化公开岗位网址、公司与岗位编号、公司与岗位名称及地点。ID 缺失或已归档返回 `404`，冲突返回 `409`，校验失败返回 `422`。客户端不得改变请求含义来绕过这些响应。

Demo 重置返回 `{"ok": true, "records_seeded": 6}`。Demo 中的 Agent 与邮件路由返回 `404`，其他模式中的重置路由返回 `404`。

## 验证

后端测试只通过仓库环境运行：

```powershell
.\.local\venv\Scripts\python.exe -m pytest app\tests -q
```

启动测试会把所需公开运行文件复制到隔离临时仓库，只终止其捕获到的服务 PID，绝不会打开正式数据库或结束端口上的任意进程。

运行前端测试与生产构建：

```powershell
pnpm --dir app\frontend test
pnpm --dir app\frontend build
```

安装锁文件兼容的 Chromium 后运行浏览器回归：

```powershell
pnpm --dir app\frontend exec playwright install chromium
pwsh -NoProfile -File .\scripts\Test-AgentBrowserE2E.ps1
```

该回归使用合成招聘页面和临时数据库，覆盖准备、fixture 上传、保存草稿、停止在提交前，以及写入待复核记录。Playwright 的 trace、screenshot 和 video 均关闭。它不读取正式数据库，也不需要真实招聘站点。

运行公开策略自测与空白检查：

```powershell
pwsh -NoProfile -File .\scripts\Test-PublicRelease.ps1 -PolicySelfTest
git diff --check
```

邮件单元测试使用确定性的 Graph/IMAP 替身，不需要真实账号。可选的无认证冒烟检查只能建立到 `imap.qq.com:993` 与 `imap.163.com:993` 的 TLS 连接，不得发送凭据，也不是必需单元测试的一部分。

## Windows CI

唯一的 CI 工作流使用 Windows、Python 3.12、Node 22、pnpm 10 与锁定依赖，运行公开发布检查、pytest、Vitest 和生产构建。CI 只有仓库内容只读权限，不配置 secrets，不连接邮箱，也不访问招聘站点。

## 排错

| 现象 | 检查方法 |
| --- | --- |
| 导入检查失败 | 确认 Python 3.12+，使用仓库环境并运行锁定同步。 |
| 前端依赖检查失败 | 使用 pnpm 10 并从锁文件安装。 |
| 启动拒绝已有监听 | 查看并停止无关进程；封装脚本不会终止未知服务。 |
| Agent 命令拒绝健康接口 | 校验服务身份、正式模式与 schema；Agent 命令绝不使用 Demo。 |
| Agent 返回 `409` | 由用户处理多条匹配、状态冲突或已结束记录的新事件。 |
| Agent 返回 `422` | 在不猜测的前提下补充必要的身份或事件日期。 |
| Demo 重置失败 | 确认 8001 是健康 Demo，并发送空 JSON 对象。 |
| 发布检查失败 | 停止发布，检查具体失败项和暂存差异，不得绕过。 |

行为边界见[申请工作流](application-workflow.zh-CN.md)、[邮件接入](mail-ingestion.zh-CN.md)与[安全与隐私](security-and-privacy.zh-CN.md)。
