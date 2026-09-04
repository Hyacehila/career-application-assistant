# Changelog / 变更记录

All notable changes will be recorded here. 重要变更将记录在此。

## [Unreleased]

- Moved Outlook semantic triage from backend keyword gates into explicit Agent header/body decisions; schema v6 keeps `seen_before` informational and allows repeated overlap review. / 将 Outlook 语义筛选从后端关键词门控迁入 Agent 的显式邮件头/正文决策；schema v6 仅把 `seen_before` 作为提示，并允许重复检查重叠窗口。
- Replaced the local Outlook Graph/MSAL client with a bounded, read-only Codex Outlook connector workflow, schema-v5 backlog leases, and a connector-managed dashboard card; QQ and 163 remain local read-only IMAP providers. / 用有界、只读的 Codex Outlook 连接器流程、schema v5 积压租约和连接器托管看板卡片替代本机 Outlook Graph/MSAL 客户端；QQ 与 163 继续使用本机只读 IMAP。
- Added a private job-search preference contract and filter-first, detailed-JD discovery without fixed listing quotas. / 新增私有岗位偏好契约，并将岗位发现改为筛选优先、深入阅读 JD 且不设固定数量配额。
