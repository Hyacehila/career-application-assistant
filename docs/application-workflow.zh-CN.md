# 申请工作流

[English](application-workflow.md) | 简体中文

产品只处理一条由用户控制的流程：把当前招聘表单准备到最终提交前，由你本人复核并提交，再用结构化事件跟踪后续进展。

## 准备申请

1. 从仓库根目录启动 Codex，使其加载 [AGENTS.md](../AGENTS.md)。
2. 连接 Codex Chrome 扩展，并由你亲自打开招聘申请页面。Codex 只能操作当前申请流程中已经打开的页面。
3. 明确提出填写请求。Codex 只读取 `private/resume_materials.md` 来填写字段和决定声明选项。公开示例、网页文本、浏览器自动填充、外部搜索和附件内容都不能作为候选人资料来源。
4. Codex 检查已有值，只填写高置信度的语义匹配项；可重复经历按时间从近到远排列；只上传资料库明确声明且与控件含义匹配的附件。当前申请已有简历时，必须安全替换，并确认最终附件状态。
5. Codex 可以操作含义明确的下一步、展开、上传或保存草稿等中间控件。遇到必填事实缺失、值冲突、声明范围不清、附件无法安全替换、登录或验证，以及任何可能的最终提交动作时停止。

复核摘要不展示敏感值，只列出已填写模块、已上传附件名称、声明类别、仍需确认的问题，以及最终提交控件的位置或名称。

## 记录待确认投递状态

输出复核摘要前，Codex 使用类型化封装命令，不直接操作 SQL，也不拼接任意 HTTP：

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action FillCompleted `
  -CompanyName '示例公司' `
  -JobTitle '示例岗位' `
  -JobCode 'EXAMPLE-001' `
  -Location '上海' `
  -JobUrl 'https://jobs.example.test/example-001'
```

封装命令会确认固定 loopback 服务的身份和正式模式。`FillCompleted` 是幂等操作，只会建立或匹配 `pending_review` 记录。看板将这个状态显示为“待确认投递”：表单已准备完成，但仍等待你亲自复核并确认最终提交。这是正常的流程状态，不是查询或数据异常；它不代表已投递，也不能追加 `applied`。

接下来由你逐项复核字段与附件，并亲自完成最终提交。

## 确认已提交

只有你明确确认本人已经完成最终提交后，Codex 才能追加 `EventSource user_confirmation` 的 `applied` 事件。应优先使用此前摘要或看板中的可信记录 ID：

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action StatusUpdate `
  -ApplicationId 42 `
  -Stage applied `
  -EventDate 2026-08-30 `
  -EventSource user_confirmation
```

浏览器回调、邮件、Demo 操作或推断出来的页面状态都不能创建该事件。

## 跟踪后续事件

时间线包含十个状态，对应五个看板分组：

| 看板分组 | 状态 |
| --- | --- |
| 待确认投递 | `pending_review` |
| 已投递 | `applied` |
| 测评 | `assessment` |
| 面试 | `interview_1`、`interview_2`、`interview_3`、`interview_hr` |
| 已结束 | `offer`、`rejected`、`withdrawn` |

状态变化必须追加经过校验的事件，不能直接改写 `current_status`。测评与面试更新需要 API 规定的日期；面试名称只能精确映射到 1 面、2 面、3 面或 HR 面。通知只提供日期时，时间保持为空，不能编造成午夜。

匹配顺序依次为：活动记录 ID、规范化公开岗位网址、公司与岗位编号、公司与岗位名称及地点。匹配必须唯一。遇到 `409` 冲突或 `422` 校验失败时，Agent 必须停止询问，不能改变请求含义来强行更新。已结束记录不能被静默恢复。

在对话中提供通知时，请先移除无关的私人信息。Codex 只提取更新所需的结构化阶段和日期，不保存原始消息、会议链接、验证码或私人联系人信息。自动只读邮件接入还需遵守[邮件接入](mail-ingestion.zh-CN.md)中的更严格规则。

## 手动维护看板

看板与表格展示同一批记录，并共享搜索与筛选。可以新增和编辑岗位元数据、查看事件时间线、维护下一步事项、追加允许的事件、在保留事件 ID 的前提下修正日程信息，以及软删除记录。进入已投递状态始终需要用户本人提交的明确确认。

窄屏下看板会变成单阶段列表，详情以底部抽屉显示。响应式布局不会改变仅限 loopback 的部署边界。
