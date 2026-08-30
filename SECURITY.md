# Security Policy / 安全策略

## Supported scope

Security fixes target the current default branch. This local application is supported only on Windows, bound to loopback, with standard data in the ignored `private/` overlay. Remote hosting, LAN exposure, shared accounts, and multi-user operation are not supported security models.

Do not put a suspected vulnerability, secret, token, real resume, raw mail, or database sample in a public issue. Use the repository platform's private security-reporting channel when it is available. If no private channel is available, open a public issue containing only a non-sensitive request for a maintainer to establish a private contact path; do not include exploit or personal-data details.

A useful private report includes the affected revision, component, impact, minimal reproduction with synthetic data, and any mitigation already tested. Maintainers should acknowledge the report through the same private channel and coordinate disclosure after a fix is available. No response-time guarantee is promised.

For deployment and data-handling controls, read [Security and privacy](docs/security-and-privacy.md).

## 支持范围

安全修复面向当前默认分支。本地应用只支持 Windows、loopback 监听，以及被忽略的 `private/` 正式数据覆盖层。远程托管、局域网暴露、共享账号和多用户运行不属于受支持的安全模型。

不要在公开 Issue 中提交疑似漏洞细节、密钥、令牌、真实简历、原始邮件或数据库样本。仓库平台提供私密安全报告通道时，应优先使用。如果没有私密通道，只能公开提出一条不含敏感信息的联系请求，请维护者建立私下沟通方式；不要附带利用细节或个人数据。

有效的私密报告应包含受影响版本、组件、影响、使用合成数据的最小复现，以及已经验证的缓解措施。维护者应在同一私密渠道确认并协调修复后的披露，但本项目不承诺固定响应时限。

部署与数据处理控制详见[安全与隐私](docs/security-and-privacy.zh-CN.md)。
