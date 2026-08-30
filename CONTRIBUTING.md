# Contributing / 贡献指南

## English

Before opening a change, read [Security and privacy](docs/security-and-privacy.md) and keep the final-submit boundary intact.

1. Create focused changes and preserve unrelated work in the tree.
2. Never add real candidate materials, application databases, mailbox data, credentials, tokens, or generated media.
3. Add or update tests for behavior changes. Run the backend suite, frontend tests, production build, and relevant PowerShell checks described in [Development](docs/development.md).
4. Stage reviewed public files by exact path. Do not use broad or forced Git adds. Run `scripts/Test-PublicRelease.ps1 -Staged` and inspect the complete staged diff.
5. Use the issue forms for reproducible bugs or bounded feature proposals. Security reports follow [SECURITY.md](SECURITY.md).

Changes that automate final submission, weaken loopback or private-overlay controls, or persist raw mail content are outside the accepted scope.

## 中文

提交变更前，请阅读[安全与隐私](docs/security-and-privacy.zh-CN.md)，并保持“最终提交必须由用户本人完成”的边界。

1. 只处理明确范围，并保留工作区中的无关改动。
2. 不得加入真实候选人资料、投递数据库、邮箱数据、凭据、令牌或生成媒体。
3. 行为变更应同步补充测试，并按[开发文档](docs/development.zh-CN.md)运行后端、前端、生产构建与相应 PowerShell 检查。
4. 按精确路径暂存已复核的公开文件，不得宽泛或强制添加。运行 `scripts/Test-PublicRelease.ps1 -Staged` 并检查完整暂存差异。
5. 可复现缺陷和范围明确的功能建议请使用 Issue Form；安全问题按 [SECURITY.md](SECURITY.md) 处理。

自动执行最终提交、削弱 loopback 或私有覆盖层控制、保存原始邮件内容的改动不在接受范围内。
