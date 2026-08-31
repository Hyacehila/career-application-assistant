# 开始使用

[English](getting-started.md) | 简体中文

## 环境要求

受支持的工作流使用 Windows、Git、PowerShell 5.1 或更高版本、Python 3.12 或更高版本、[`uv`](https://docs.astral.sh/uv/) 和 [`pnpm`](https://pnpm.io/)。下文命令使用 PowerShell 7 提供的 `pwsh`；使用 Windows PowerShell 5.1 时，请替换为 `powershell.exe`。正式模式与 Demo 都只监听 loopback。

可以随时运行固定检查项的环境自检：

```powershell
pwsh -NoProfile -File .\scripts\Test-Environment.ps1 -Mode Standard
pwsh -NoProfile -File .\scripts\Test-Environment.ps1 -Mode Demo
```

自检只输出检查名与 PASS/FAIL，不输出候选人资料、凭据、附件名、用户名或绝对用户路径。

## 安装依赖

在仓库根目录执行：

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --locked --extra dev
pnpm --dir app\frontend install --frozen-lockfile
pnpm --dir app\frontend build
```

`uv.lock` 与 `app/frontend/pnpm-lock.yaml` 是可复现依赖输入。本地环境、缓存和前端构建产物被 Git 忽略。

## 启动合成 Demo

不创建私有覆盖层、不连接邮箱，也可以直接体验产品：

```powershell
pwsh -NoProfile -File .\scripts\Start-Demo.ps1
```

打开 [http://127.0.0.1:8001](http://127.0.0.1:8001)。前台进程会在系统临时根目录的直接子目录中创建经过校验的会话目录，并写入六条虚构记录。按 Ctrl+C 后只清理该会话目录。

如果 8001 已由健康 Demo 占用，普通启动会幂等成功返回，不会创建第二个进程。可以从页面重置，也可以在另一个终端执行：

```powershell
pwsh -NoProfile -File .\scripts\Start-Demo.ps1 -Reset
```

8001 上的未知服务会被拒绝。Demo 不初始化 `private/`，不构造邮件运行时，也不暴露邮件和 Agent 路由。

## 启动正式模式

初始化私有覆盖层：

```powershell
pwsh -NoProfile -File .\scripts\Initialize-PrivateOverlay.ps1
```

命令会分别从公开示例模板初始化 `private/resume_materials.md` 和 `private/job_search_preferences.md`。目标文件已存在时只报告状态，不读取或替换；缺失时才创建。`private/` 中的其他文件不会被枚举、修改或删除。

补全两个生成文件；岗位偏好文件只用于发现范围和排序，附件只按简历资料文件中的声明加入。然后在不输出真实值的前提下校验工作区：

```powershell
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private -InitializeResumeHash
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private
```

以前台方式启动服务：

```powershell
.\.local\venv\Scripts\python.exe app\server.py
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。正式模式只接受 `private/applications.sqlite`。数据库缺失时只在该位置创建；版本不受支持时停止启动，不覆盖数据。

Agent 工作流使用的幂等后台入口为：

```powershell
pwsh -NoProfile -File .\scripts\Start-BoardService.ps1
```

它会校验健康接口中的服务身份和正式模式，仅在需要时启动固定本机服务，并拒绝 Demo 或未知服务。

## 前端开发

让正式 API 保持运行在 8000，然后单独启动 Vite：

```powershell
pnpm --dir app\frontend dev
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)，Vite 会把 `/api` 代理到正式本机服务。

## 常见启动问题

| 现象 | 检查方法 |
| --- | --- |
| 私有覆盖层检查失败 | 运行初始化脚本，再在不输出私密值的前提下修复缺少的占位项或声明。 |
| 找不到本地 Python | 创建 `.local/venv`，设置 `UV_PROJECT_ENVIRONMENT`，再运行锁定依赖同步。 |
| `/` 只显示构建提示 | 构建前端后重启后端进程。 |
| 健康检查返回 `503` | 检查写入权限和受支持的数据库版本；不要自动删除或替换数据库。 |
| 8000 或 8001 端口被拒绝 | 停止无关监听进程；脚本不会终止未知服务。 |
| 邮件安全存储不可用 | 使用受支持的 Windows 交互用户会话；服务不会回退到明文保存。 |

下一步可阅读[申请工作流](application-workflow.zh-CN.md)或[开发与 API 参考](development.zh-CN.md)。
