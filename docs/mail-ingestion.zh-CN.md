# 邮件接入

[English](mail-ingestion.md) | 简体中文

邮件接入是正式模式中可选的只读后台能力，不是收件箱客户端。Demo 不构造邮件服务，也不挂载 `/api/mail/*`。

## 支持的服务商

| 服务商 | 连接方式 | 增量游标 | 密钥保存位置 |
| --- | --- | --- | --- |
| Outlook / Outlook.com | Microsoft Graph 用户委托 `Mail.Read`，公共客户端授权码流程与 PKCE | Inbox delta link | 本地应用数据目录中由 Windows DPAPI 加密的 MSAL 缓存 |
| QQ 邮箱 | 993 端口 TLS IMAP 与单独生成的授权码 | `UIDVALIDITY` 与最后处理 UID | Windows Credential Manager |
| 163 邮箱 | 993 端口 TLS IMAP 与客户端授权密码 | `UIDVALIDITY` 与最后处理 UID | Windows Credential Manager |

实现中没有 SMTP、发送、回复、转发、删除、移动、标记已读、附件下载或 webhook。服务商凭据与令牌不会写入 SQLite、配置文件、日志或 `private/`。Windows 安全存储不可用时会连接失败，不会回退到明文。

## Outlook 设置

请注册 Microsoft Entra 公共客户端应用。需要支持 Outlook.com 时，应允许个人 Microsoft 账号；将 `http://localhost` 配置为移动/桌面应用重定向 URI，并且只添加用户委托的 `Mail.Read`。本地界面填写公开 Client ID，不使用客户端密钥。

MSAL 使用 PKCE 完成交互授权，并通过 DPAPI 保护的缓存刷新令牌。Inbox 增量读取遵循 Microsoft Graph [邮件增量查询 API](https://learn.microsoft.com/zh-cn/graph/api/message-delta?view=graph-rest-1.0)。认证实现使用 [MSAL Python](https://github.com/AzureAD/microsoft-authentication-library-for-python)，许可信息见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

登录、账号恢复、验证码、多因素验证和外部授权必须由用户亲自完成。应用不会读取或填写验证码。

## QQ 邮箱与 163 邮箱设置

在服务商设置中启用 IMAP，并生成专用客户端授权码或授权密码。不要输入网页版登录密码。可参考 [QQ 邮箱连接说明](https://hiflow.tencent.com/docs/applications/qq-mail/) 与[网易邮箱帮助](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2ed007f2b27412aae)。

服务只通过 993 端口的校验 TLS 连接，以只读 `EXAMINE` 打开 Inbox，并使用 UID 查询和 `BODY.PEEK`。代码没有邮箱写入接口。

## 增量处理

首次连接默认只读取新消息，也可以明确选择回溯 30 天或 90 天。单个进程内调度器按有界间隔轮询已连接账号。

每轮先读取有限的头部元数据。只有命中招聘通知高召回规则时，才把有大小限制且不是附件的文本正文读入内存。HTML 只离线转换为纯文本；邮件中的脚本、远程资源、链接和指令都不会被执行。

游标只能与本轮结构化结果在同一成功事务中推进。读取、解析或写入失败时保持不变。`UIDVALIDITY` 变化或 Graph delta link 失效时，只做有界重叠窗口重建，不进行无界邮箱扫描。

## 提取与自动更新

只有测评和精确的 1 面、2 面、3 面或 HR 面才可能自动追加，而且必须同时满足：

- 按既定优先级唯一匹配到一条活动申请；
- 必需的事件、计划或截止日期明确；
- 状态迁移安全且一致；
- 可信度达到服务阈值。

泛化面试、日期歧义或冲突、没有匹配或多条匹配、`applied`、Offer、拒绝、撤回、归档申请、已结束记录的新流程和不安全迁移都会留在人工复核队列。`applied` 始终要求用户亲自最终提交后的 `user_confirmation` 事件。

邮件文本是不可信输入，不能改变本地规则、数据库结构、安全存储边界或应用命令。

## 结构化复核队列

候选待复核期间只保留公司、岗位、建议阶段、事件/计划/截止日期、可信度、匹配记录 ID、原因码、服务商/指纹和最小队列元数据。API 与前端不展示主题、发件人、正文、附件、会议链接、验证码或私人联系人。

确认安全候选后追加经过校验的事件。忽略、去重或过期会立即清除可读结构化字段，只保留最小审计与去重元数据。未处理候选在 90 天后过期。断开连接会删除服务商游标及相应安全凭据或令牌缓存。

## 操作与排错

“邮件接入”视图只显示脱敏连接状态、同步控件和结构化候选。暂停会保留安全连接与游标；恢复会请求下一轮有界同步；断开会删除这些内容。

| 现象 | 检查方法 |
| --- | --- |
| Outlook 再次要求授权 | 检查公共客户端、`http://localhost` 重定向和用户委托 `Mail.Read`，再重新连接。 |
| QQ/163 认证失败 | 确认已开启 IMAP，并使用生成的授权码而不是网页版密码。 |
| 安全存储失败 | 在 Credential Manager 与 DPAPI 可用的 Windows 交互用户会话中运行。 |
| 候选未自动写入 | 查看原因码；歧义和不安全迁移会有意交给人工。 |
| 同步重复旧邮件 | 检查是否发生 `UIDVALIDITY` 或 delta 失效后的有界游标重建；不要手动重置或扫描邮箱。 |

公开 API 操作见[开发与 API 参考](development.zh-CN.md)，持久化限制见[安全与隐私](security-and-privacy.zh-CN.md)。
