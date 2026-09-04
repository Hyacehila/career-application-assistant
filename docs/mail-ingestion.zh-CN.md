# 邮件接入

[English](mail-ingestion.md) | 简体中文

邮件接入是正式模式中的可选只读能力，不是收件箱客户端。Demo 不构造邮件服务，也不挂载 `/api/mail/*`。

## 支持的服务商

| 服务商 | 连接方式 | 增量状态 | 密钥保存位置 |
| --- | --- | --- | --- |
| Outlook / Outlook.com | Codex Outlook Email 连接器 | 固定 Inbox 扫描窗口、重叠水位与持久化积压 | 由 Codex 连接器管理；本机不缓存令牌 |
| QQ 邮箱 | 993 端口 TLS IMAP 与单独生成的授权码 | `UIDVALIDITY` 与最后处理 UID | Windows Credential Manager |
| 163 邮箱 | 993 端口 TLS IMAP 与客户端授权密码 | `UIDVALIDITY` 与最后处理 UID | Windows Credential Manager |

本机 Python 服务不再包含 Outlook Graph 客户端、Entra 应用注册、MSAL 依赖、Client ID 或 Outlook 令牌缓存。系统也没有 SMTP、发送、回复、转发、草稿、删除、移动、标记已读、分类、附件下载或 webhook 功能。

## Outlook 连接器设置

在 Codex 中连接 Outlook Email，登录或重新授权必须由用户亲自完成。连接器权限保持当前设置；本仓库通过 `AGENTS.md` 与[仓库级 skill](../.agents/skills/outlook-recruitment-sync/SKILL.md)把实际行为收窄为只读。

每次在本仓库开启新的 Codex 任务时，skill 会先尝试一次有界同步，再继续处理用户请求。这里没有定时任务或持续后台监听。连接器已暂停、已有有效租约或邮箱没有结构化变化时保持安静；失败只提示脱敏错误码，不阻塞当前任务。

skill 只能调用列举文件夹、列举邮件和批量取信三个动作，并且只认 `wellKnownName=inbox` 的 Inbox。若插件运行时在全部文件夹上省略该规范字段，只允许改用 Graph 的固定 well-known 标识符 `inbox`，绝不按显示名称或路径猜测。禁止发送、草稿、回复、转发、移动、删除、分类、标记已读、退订、附件访问、打开链接或执行邮件指令。

## Outlook 有界协议

1. `POST /api/mail/outlook-connector/runs` 申请 15 分钟独占租约，最多返回两个固定扫描窗口。
2. 首次最多覆盖最近 30 天；后续优先处理最新重叠窗口，同时保留未完成的历史积压。
3. 每个任务最多处理 200 封邮件头，最新增量优先；后端逐窗口校验分页偏移。
4. `.../headers` 只接收有界的主题、发件人、时间和来源 ID，并为每个校验通过的邮件头签发一个服务端一次性决策 token。`seen_before` 只是指纹历史事实，不是后端跳过决定。
5. Agent 查看每个邮件头后显式选择 `fetch` 或 `skip_header`。所选邮件按最多 20 封一批取正文；Agent 阅读正文后再显式选择 `process` 或 `skip_body`。后端和编排 JavaScript 都不得用关键词规则替 Agent 作这两层语义判断。
6. 单封正文 UTF-8 上限 512 KiB，每个提交批次上限 2 MiB；仅对 Agent 批准处理的 HTML 在本机离线转纯文本。每个邮件头都取得 Agent 决策后，`.../complete` 才能推进完整窗口；`.../fail` 只能用白名单错误码释放租约。

原始连接器响应、消息 ID 和临时 token 只留在私有编排状态中。有界的邮件头与正文审阅包会进入当前 Codex 任务上下文供 Agent 判断，但不会在普通状态输出中复述。邮件 JSON 经标准输入送入[固定封装脚本](../scripts/Invoke-OutlookConnectorSync.ps1)，绝不进入命令行参数或临时文件；交互终端会关闭回显与行缓冲，脱敏响应用有序短帧返回，避免控制台换行破坏 JSON。列表调用顺带返回的正文、收件人、附件标记与链接会被丢弃。

## QQ 邮箱与 163 邮箱

在服务商设置中启用 IMAP，并生成专用授权码或客户端授权密码，不要输入网页版登录密码。可参考 [QQ 邮箱说明](https://hiflow.tencent.com/docs/applications/qq-mail/)与[网易邮箱帮助](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2ed007f2b27412aae)。

服务只通过 993 端口的校验 TLS 连接，以只读 `EXAMINE` 打开 Inbox，并使用 UID 查询和 `BODY.PEEK`。只有 QQ/163 使用本机调度器以及连接、同步和断开 API。

## 提取与持久化

只有经 Agent 明确批准处理的邮件才进入确定性提取。只有测评和精确的 1 面、2 面、3 面或 HR 面才可能自动追加，而且必须同时满足：唯一匹配活动申请、必需日期明确、状态迁移安全且可信度达到阈值。

泛化面试、日期歧义或冲突、没有匹配或多条匹配、`applied`、Offer、拒绝、撤回、归档申请、已结束记录的新流程和不安全迁移都会留在人工复核队列。`applied` 始终要求用户亲自完成最终提交后产生 `user_confirmation` 事件。

SQLite 与 API 响应绝不包含原始主题、发件人、正文、消息 ID、收件人、附件、验证码、会议链接或连接器 token。待复核候选只含有界结构化字段；确认、忽略、去重或 90 天过期后立即清除可读候选字段，只保留最小审计与指纹数据。

邮件与 HTML 都是不可信输入，不能改变仓库规则、数据库结构、凭据、安全边界或命令，也不会加载外部资源。

## 界面与排错

Outlook 卡片明确显示“由 Codex Outlook 连接器管理”，只提供暂停/恢复，以及脱敏成功时间、错误和待复核数量。QQ/163 继续提供本机连接、同步、暂停/恢复和断开操作。

| 现象 | 检查方法 |
| --- | --- |
| Outlook 需要登录 | 在 Codex 中完成 Outlook 连接器登录或重新授权；本机不再有 Client ID 表单。 |
| Outlook 启动同步没有提示 | 静默表示已暂停、已有租约或没有结构化变化；需要时查看卡片状态。 |
| QQ/163 认证失败 | 确认已开启 IMAP，并使用生成的授权码而不是网页版密码。 |
| 候选未自动写入 | 查看原因码；歧义与不安全迁移会有意交给人工。 |
| 同步中断 | 后续新建 Codex 任务即可重试；租约过期后恢复，未完成窗口不会推进游标。 |

v5 迁移会删除旧 Outlook 账户行、Graph 游标和 Outlook 复核候选，但保留已经提交到申请时间线的事件。v6 迁移会释放 v5 的临时连接器租约，并允许为重复邮件头签发独立决策 token，避免重叠窗口或 `seen_before` 提示阻止 Agent 复核。启动时还会在固定的本地应用数据目录下，只删除命名严格匹配的旧 MSAL 缓存；路径不安全或删除失败时会中止启动。

公开 API 见[开发与 API 参考](development.zh-CN.md)，持久化限制见[安全与隐私](security-and-privacy.zh-CN.md)。
