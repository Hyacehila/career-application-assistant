# 求职投递助手

[English](README.md) | 简体中文

这是一个面向本地单用户的求职工作区，将受约束的招聘表单填写、AI 辅助状态更新和投递看板放在同一套流程里。Agent 可以准备申请页面并维护投递时间线，但最终复核和正式提交始终由用户本人完成。

> [!IMPORTANT]
> 私有文件位于 Git 忽略的 `private/` 覆盖层中，并不是加密保险箱。请保护本地工作区，按需排除备份或同步工具，并在发布变更前执行公开发布检查。

## 项目实现了什么

| 范围 | 已实现的行为 |
| --- | --- |
| 表单辅助 | Codex 只读取 `private/resume_materials.md`，填写 Chrome 中已打开的招聘页面，上传明确声明的附件，并在最终提交前停止。 |
| Agent 入库 | 表单准备完成后，Agent 检查或启动本地 API，并幂等创建 `pending_review`（待人工复核）记录。 |
| 状态跟踪 | 用户确认已投递，以及后续测评、面试、Offer、拒绝或撤回，都会作为经过校验的时间线事件追加。 |
| 本地看板 | React 看板和表格支持搜索、筛选、排序、分页、拖拽更新阶段、详情抽屉、下一步事项和软删除。 |
| 本地数据 | FastAPI 只向 `private/applications.sqlite` 写入一个 SQLite 数据库；生产环境不接受任意数据库路径。 |
| 安全边界 | API 仅监听本机，拒绝非 JSON 写请求和异常 Host，校验日期与状态变更；填表回调永远不能把记录标记为已投递。 |

系统使用 10 个精确状态，并归入 5 个看板分组：

| 看板分组 | 精确状态 |
| --- | --- |
| 待人工复核 | `pending_review` |
| 已投递 | `applied` |
| 笔试 / 测评 | `assessment` |
| 面试 | `interview_1`、`interview_2`、`interview_3`、`interview_hr` |
| 已结束 | `offer`、`rejected`、`withdrawn` |

## 项目明确不做什么

- 不点击“提交申请”“确认”“发送”或任何含义相同的最终操作。
- 不自动读取邮箱，也不连接邮箱账号。需要更新状态时，由用户提供对应通知。
- 不处理自动登录、验证码、身份验证、账号注册、付费、背景调查同意或外部授权。
- 不爬取岗位、不推荐职位、不发送通知、不同步日历，也不执行无人值守的批量投递。
- 不提供用户账号、云同步、远程访问或多人部署。
- SQLite 不保存简历内容、候选人联系方式、表单答案、附件、邮件正文、验证码或会议链接。

## 系统结构

```text
private/resume_materials.md ──> Codex ──> 已打开的招聘页面
                                  │         （最终提交前停止）
                                  │
                                  └──────> 本地 JSON API ──> private/applications.sqlite
                                                     ▲
                                                     │
                                              React 看板 / 表格
```

`AGENTS.md` 规定 Agent 的浏览器操作、隐私、附件替换、冲突处理和数据库写入规则。看板界面与 Agent 使用同一个 HTTP API；Agent 不得直接执行 SQL。

## 快速开始

### 环境要求

当前文档和测试采用 Windows 环境：

- Git；
- PowerShell 5.1 或更高版本（示例使用 `pwsh`）；
- Python 3.12 或更高版本；
- [`uv`](https://docs.astral.sh/uv/)；
- [`pnpm`](https://pnpm.io/)。

### 1. 创建私有覆盖层

在全新克隆中执行一次：

```powershell
pwsh -NoProfile -File .\scripts\Initialize-PrivateOverlay.ps1
```

脚本会根据公开占位模板创建 `private/resume_materials.md`。如果 `private/` 已经包含文件，脚本会停止，不会覆盖现有资料。

补全生成的资料文件，只将其中明确声明的附件放入 `private/`，然后校验私有工作区：

```powershell
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private -InitializeResumeHash
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private
```

校验器只输出检查项和通过/失败结果，不打印个人资料。简历哈希用于确认预期附件，哈希状态文件同样被 Git 忽略。

### 2. 安装依赖并构建前端

在仓库根目录执行：

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --extra dev
pnpm --dir app\frontend install
pnpm --dir app\frontend build
```

依赖由 `uv.lock` 和 `app/frontend/pnpm-lock.yaml` 约束。本地环境、缓存和前端构建产物不会进入 Git。

### 3. 启动应用

```powershell
.\.local\venv\Scripts\python.exe app\server.py
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。一个进程同时提供 API 和已构建前端，并且只监听本机。数据库缺失时只会在 `private/applications.sqlite` 初始化；数据库版本未知或不兼容时，服务会停止，而不是覆盖数据。

Agent 使用的幂等启动入口为：

```powershell
pwsh -NoProfile -File .\scripts\Start-BoardService.ps1
```

脚本先检查 `/api/health`，必要时在隐藏的本机窗口启动服务，并等待约 10 秒。它不会安装依赖、下载内容或删除文件。

## 使用看板

默认页面是五阶段看板，同一批记录也可以切换为九列表格。两种视图共享搜索和筛选条件，页面状态会写入 URL。

- 可以在界面中新增或编辑记录，公司与岗位为必填项。
- 点击卡片或表格行，可以查看记录 ID、岗位信息、当前进度、事件时间线和下一步事项。
- 通过状态表单或拖动卡片更新阶段。进入“已投递”前必须确认用户已经亲自提交；测评和面试必须提供相应日期。
- 可以修正事件日期和详情，同时保留原事件 ID。
- 界面删除采用软删除，历史事件继续保留。

屏幕宽度小于 768 px 时，看板会变成单阶段列表，详情使用底部抽屉。响应式布局只用于本机窄屏显示，不会开放局域网访问。

## 让 Codex 直接辅助写入数据库

请从仓库根目录开始 Codex 任务，确保它能读取 `AGENTS.md`。需要填写招聘页面时，先连接 Codex Chrome 扩展，并由你亲自打开目标申请页面，然后直接提出类似请求：

> 按照 `AGENTS.md` 填写当前打开的招聘申请页面，在最终提交前停止，并把已准备好的申请记录到本地看板。

完整闭环如下：

1. Codex 只根据 `private/resume_materials.md` 填写高置信度字段，并在需要时替换当前申请的简历附件。
2. 输出复核摘要前，使用 `scripts/Invoke-BoardAgent.ps1 -Action FillCompleted` 写入岗位元数据。该命令统一执行健康检查、必要时调用 `Start-BoardService.ps1`，并请求 `POST /api/agent/fill-completed`。
3. 新记录只能是 `pending_review`，不能直接成为 `applied`；命令输出只包含记录 ID、动作和当前状态。
4. 你亲自复核页面并完成正式提交。
5. 只有在你明确说明“我已经亲自提交了这份申请”之后，Codex 才能使用同一封装命令按记录 ID 追加来源为 `user_confirmation` 的 `applied` 事件。

封装命令只接受具名参数，不接受原始 JSON、数据库路径、其他主机或任意接口。例如：

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action FillCompleted `
  -CompanyName '示例公司' `
  -JobTitle '示例岗位' `
  -JobCode 'EXAMPLE-001' `
  -Location '上海' `
  -JobUrl 'https://jobs.example.test/example-001'

pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action StatusUpdate `
  -ApplicationId 42 `
  -Stage interview_1 `
  -EventDate 2026-08-29 `
  -ScheduledDate 2026-09-02 `
  -EventSource email_extract
```

后续跟踪时，提供公司/岗位上下文和对应通知即可。例如：

> 我收到了这份申请的测评通知。只提取阶段和日期，更新唯一匹配的看板记录，不要保存原始邮件内容。

只有活动记录唯一匹配、阶段明确、必需日期齐全时，Codex 才能写入。状态更新优先使用此前返回或看板显示的记录 ID；没有可信 ID 时才使用岗位元数据匹配。邮件更新必须使用 `email_extract`，面试轮次必须明确映射为 1 面、2 面、3 面或 HR 面。缺少日期、轮次名称不符合规则、匹配到多条、已结束记录发生冲突或 API 报错时，Agent 必须停止询问，不能猜测。

本地应用只保存结构化结果。不过，用户提供的消息仍会在 Codex 对话中被处理；与匹配和状态无关的私人内容，建议先行删除。

## API 概览

所有接口都位于 `/api` 下并返回 JSON。POST 和 PATCH 请求必须使用 `Content-Type: application/json`。

| 方法 | 接口 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 检查服务、数据库和迁移版本 |
| `GET` | `/api/applications` | 返回分页记录、筛选选项和五组看板计数 |
| `POST` | `/api/applications` | 手动建立待人工复核记录 |
| `GET` | `/api/applications/{id}` | 返回岗位详情和事件时间线 |
| `PATCH` | `/api/applications/{id}` | 编辑元数据、备注和下一步；不能直接改状态 |
| `DELETE` | `/api/applications/{id}` | 软删除记录 |
| `POST` | `/api/applications/{id}/events` | 追加经过校验的状态事件，并在事务中更新当前状态 |
| `PATCH` | `/api/applications/{id}/events/{event_id}` | 修正事件日程，同时保留事件 ID |
| `POST` | `/api/agent/fill-completed` | 幂等记录已完成填写、待用户复核的申请 |
| `POST` | `/api/agent/status-update` | 唯一匹配活动记录并追加结构化状态事件 |

Agent 状态匹配顺序为：活动记录 ID；规范化公开岗位网址；公司与岗位编号；公司、岗位与地点。记录 ID 是最高优先级精确匹配，已归档或不存在的 ID 返回 `404`。其他匹配冲突返回 `409`，必填信息缺失或不合法返回 `422`。Agent 不得为了绕过错误而改变原请求语义。

## 数据与隐私模型

### 会进入 Git 的公开内容

- `app/` 中的应用代码和测试；
- `scripts/` 中的初始化、启动与安全检查脚本；
- `AGENTS.md`、中英文 README、依赖锁文件、许可证和纯占位模板。

### 只保留在本机的忽略内容

- `private/resume_materials.md`；
- `private/applications.sqlite` 以及其他 SQLite 文件；
- 简历、照片、文档和图片附件；
- `.resume.sha256`、本地虚拟环境、缓存、编辑器状态和构建输出。

SQLite 只保存岗位元数据、当前状态、结构化事件日期、短备注和下一步事项，不是候选人资料库。API 会从公开岗位网址中移除查询参数和片段，并拒绝未定义的请求字段。

需要备份时，应先停止服务，再将 `private/applications.sqlite` 复制到另一个受保护的本地位置。不要把备份放入 Git。Git 忽略规则不会阻止操作系统备份或云盘同步 `private/`，这些系统需要单独配置。

不要通过反向代理、端口转发、隧道或局域网绑定暴露 8000 端口。系统没有用户认证，因为唯一支持的部署方式是本机 loopback。

## 安全公开仓库

只显式暂存预期公开路径。不要使用 `git add .`、`git add -A` 或 `git add -f`：

```powershell
git add -- README.md README.zh-CN.md
# 其他公开文件也要逐个写出并确认准确路径，不要一次暂存整个目录。
pwsh -NoProfile -File .\scripts\Test-PublicRelease.ps1 -Staged
git diff --cached --check
git diff --cached --name-only
git diff --cached
```

发布检查会校验公开路径白名单，并拒绝私有路径、数据库、常见附件类型、可识别密钥、个人联系方式模式、未跟踪文件和缺失的必要规则。该脚本是一道防线，不是对所有自然语言内容的数学证明；提交前仍需人工查看完整暂存差异，检查失败时不得绕过。

## 开发与验证

使用仓库虚拟环境运行后端测试：

```powershell
.\.local\venv\Scripts\python.exe -m pytest app\tests -q
```

运行前端测试和生产构建：

```powershell
pnpm --dir app\frontend test
pnpm --dir app\frontend build
```

首次运行浏览器闭环测试前安装锁文件对应的 Chromium，然后执行统一测试入口：

```powershell
pnpm --dir app\frontend exec playwright install chromium
pwsh -NoProfile -File .\scripts\Test-AgentBrowserE2E.ps1
```

该测试在系统临时目录创建隔离 SQLite，模拟“填写字段→上传测试附件→保存草稿→停止在提交前→通过 Agent 命令写入待复核”，结束后关闭测试服务并删除临时数据，不读取真实 `private/` 数据库。

开发前端时，保持 API 运行在 8000 端口，并在另一个终端启动 Vite：

```powershell
pnpm --dir app\frontend dev
```

打开 `http://127.0.0.1:5173`；Vite 会把 `/api` 代理到本地 FastAPI 服务。

后端目录结构和启动说明见 [app/README.md](app/README.md)。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 启动时提示缺少私有覆盖层 | 从仓库根目录运行 `Initialize-PrivateOverlay.ps1`。 |
| 启动脚本找不到 Python | 建立 `.local/venv`，并执行 `uv sync --extra dev`。 |
| 打开 `/` 只看到构建提示 | 执行 `pnpm --dir app\frontend build`，然后重启服务。 |
| 健康检查返回 `503` | 检查 `private/` 是否可写、数据库版本是否受支持；不要自动删除或替换数据库。 |
| Agent 收到 `409` | 可能匹配到多条记录、状态冲突，或已结束记录收到新流程事件；需要由用户判断。 |
| Agent 收到 `422` | 岗位身份、面试日期、测评计划/截止日期或其他校验字段缺失或不合法。 |
| 私有工作区检查失败 | 在不打印真实值的前提下，处理未替换占位符、附件声明、经历顺序或简历哈希变化。 |
| 公开发布检查失败 | 停止发布，查看失败项并修正暂存内容，不要绕过检查。 |

## 开源许可

本项目采用 [MIT License](LICENSE)。
