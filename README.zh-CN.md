# X-Agent AI MCP 黑客松 2026 与 Agent 插件

[English](./README.md) | 简体中文 | [日本語](./README.ja.md)

[![X-Agent AI MCP 黑客松 2026：9 月 2 日至 10 月 4 日，总奖池 1,000 USDT 和 100,000 X-Points](https://xagt.ai/hackathon/og-cover.jpg)](https://xagt.ai/hackathon?lang=zh)

> **构建真实可用、可验证的 Agent 与 MCP 应用。两个赛道，总奖池 1,000 USDT + 100,000 X-Points。活动时间：2026 年 9 月 2 日至 10 月 4 日。**

本仓库是 X-Agent AI MCP 黑客松 2026 的官方代码提交入口，同时包含 `@xagt/agent-plugin` 安装工具。

[活动介绍与规则](https://xagt.ai/hackathon?lang=zh) · [Luma 报名](https://luma.com/h0qt02e4) · [Telegram 社群](https://t.me/XAgent_official)

往期活动：[X-Agent × OKX Agentic Wallet Hackathon · 2026 年 5 月](./docs/archive/2026-xagent-okx-agentic-wallet-hackathon.md) · [代码与提交归档](./submissions/INDEX.md)

## 当前活动：X-Agent AI MCP 黑客松 2026

面向全球开发者和团队，欢迎围绕 AI、加密领域、数据、自动化和 Agent 基础设施构建实用应用。请从**两个赛道中选择一个**，统一通过本仓库提交，两个赛道分别评奖。当前活动的时间、奖励与赛道规则以[活动页](https://xagt.ai/hackathon?lang=zh)为准。

### 选择你的赛道

| 赛道 | 构建内容 | 赛道奖池 |
| --- | --- | --- |
| **开放创新挑战赛（General Challenge）** | 构建原创、实用且由 API 支持的 Agent 或 MCP 能力，完成部署并提供真实、可验证的调用。 | 500 USDT + 50,000 X-Points |
| **OlaXBT × X-Agent 交易挑战赛** | 使用 OlaXBT Nexus MCP 进行策略开发、回测、绩效分析和市场数据调用。验证交易策略后，基于策略开发自己的 Agent 或 MCP 应用。 | 500 USDT + 50,000 X-Points |

OlaXBT 为交易赛道赞助方。**仅提交策略、回测报告或简单的 API 封装，不算完整交易赛道作品。** 请先阅读 [Nexus MCP 文档](https://nexus.olaxbt.xyz/api/mcp/docs)和[交易挑战赛规则与开发指南](https://xagt.ai/hackathon/olaxbt-guide?lang=zh)。

**两个赛道均不接受：** 链上安全与审计类项目，包括智能合约审计、漏洞或攻击检测、钱包或交易风险评分、钓鱼/诈骗/Rug Pull 检测、安全监控，以及合规或安全分析等。

提交前**不要求自行开发 MCP Server**，但必须提供可运行的能力、已部署 API 和完整源码。交易赛道仍须使用 OlaXBT Nexus MCP，这项要求不因此免除。

### 活动时间安排

**2026.09.02 — 2026.10.04**

| 阶段 | 日期 | 内容 |
| --- | --- | --- |
| 报名与开发阶段 | 2026.09.02 — 2026.09.19（18 天） | 报名与开发同步开放。参赛者可组建团队、参加技术入门和社区问答，并完成项目开发、部署、测试和提交。 |
| 技术审核与评审 | 2026.09.20 — 2026.10.01（12 天） | 完成资格检查、API 验证、源码审核和项目评分。 |
| 结果公布 | 2026.10.02 — 2026.10.04（3 天） | 通过 X-Agent 官方渠道和社区公布最终结果。 |

### 奖励与项目支持

总奖池为 **1,000 USDT + 100,000 X-Points**。每个赛道分别发放：

| 各赛道名次 | USDT | X-Points |
| --- | --- | --- |
| 第一名 | 500 | 15,000 |
| 第二名 | — | 12,000 |
| 第三名 | — | 10,000 |
| 第四名 | — | 8,000 |
| 第五名 | — | 5,000 |

奖励按团队发放，不向每位成员重复发放。入选项目还有机会获得 MCP 标准化、市场接入、生态曝光及付费调用变现支持。支持不代表保证上架、收入或获得 OKX、OKX.AI 背书。

### 一条流程看懂活动

```text
报名、选择赛道并开发可调用的真实能力
        ↓
通过 PR 提交已部署 API 与完整源码
        ↓
验证 API、提交版本、源码与安全性，并进行评审
        ↓
入选项目：获得 X-Agent 的 MCP 标准化支持
        ↓
市场与生态接入支持
```

评审对象是能够实际运行的能力，而不是创意 PPT。X-Agent 提供支持不代表 OKX 一定接受、上架、提供流量、产生收入或作出背书。

### 最低提交要求

每个项目必须包含：

1. **已部署 API**：评审期间可以真实调用。
2. **公开健康检查接口**：返回本次评审对应的准确 Git Commit。
3. **完整源码**：通过 Pull Request 提交到本仓库。
4. **固定的公开 GitHub Commit**：与线上服务版本一致。
5. **可复现说明**：包括安装、测试、部署和一次真实 API 调用。
6. **部署证明接口**：把线上服务与项目 slug、Commit 绑定。
7. **安全、数据、依赖与权利声明**：足以支持安全评审和长期归档。

提交时不要求自行实现 MCP Server、Streamable HTTP、x402、EIP-3009、A2MCP 或支付 SDK。交易赛道仍须按上述规则使用 OlaXBT Nexus MCP。

### 代码提交位置

每个 Pull Request 只能新增一个项目目录：

```text
submissions/mcp-hackathon/<团队或开发者>-<项目名称>/
├── SUBMISSION.md          # 能力、API、Commit 与运行说明
├── submission.json        # 机器可读的源码和部署绑定信息
├── RIGHTS.md              # 所有权与归档授权声明
├── source/                # 用于评审的完整源码
└── verification/
    └── README.md          # 可重复执行的 API 验证证据
```

只提供外部 GitHub 链接不算完整提交。请在 `source/` 中放入实际源码，同时提供依赖清单及适用的锁文件、不含密钥的配置示例，以及安装、构建和运行说明。说明项目依赖的外部 API 或私有服务。只有 README、子模块、文件链接或 Git LFS 指针，不能代替源码文件。官方归档确认完成后，删除原仓库不会删除已归档的副本。

请从以下文件开始：

- [`完整提交规范`](./submissions/README.md)
- [`submissions/TEMPLATE.md`](./submissions/TEMPLATE.md)
- [`submissions/submission.example.json`](./submissions/submission.example.json)
- [`submissions/RIGHTS_TEMPLATE.md`](./submissions/RIGHTS_TEMPLATE.md)
- [`submissions/VERIFICATION_TEMPLATE.md`](./submissions/VERIFICATION_TEMPLATE.md)

### 使用 Codex、Claude Code 或其他编码 Agent 提交

欢迎使用 Vibe Coding 完成的项目。编码 Agent 可以整理源码、验证线上版本、运行官方检查并创建 PR，但真实性和证据要求不会降低。

把下面的提示词复制到 Codex、Claude Code、Cursor、OpenCode 或其他编码 Agent：

```text
将当前目录中的项目提交到 X-Agent MCP 黑客松。
遵循 https://github.com/xagentAI/xagt-plugin/blob/main/docs/agent-submission-guide.md
以及其中链接的官方提交 Skill。

我授权你 Fork xagentAI/xagt-plugin、创建分支、推送验证后的提交包并创建
Pull Request。不得泄露密钥，也不得伪造 API、部署状态、Commit、测试或
所有权证据。如果缺少真实证据，请停止提交并告诉我缺少什么。
```

仓库为 Codex 提供 [`AGENTS.md`](./AGENTS.md)，为 Claude Code 提供 [`CLAUDE.md`](./CLAUDE.md)，并包含可复用的 [`xagt-submit-hackathon` Skill](./skills/xagt-submit-hackathon/SKILL.md)。请在提示词中补充项目名称、公开仓库、准确的线上 Commit、API 地址和健康检查地址。完整版本请阅读 [`编码 Agent 提交指南`](./docs/agent-submission-guide.md)。

### 四步完成提交

先通过 [Luma 报名](https://luma.com/h0qt02e4)并选择赛道，再于 9 月 2–19 日的开发期内完成以下步骤：

1. 开发并部署 API，确认健康检查和一次真实能力调用成功。
2. Fork 本仓库并创建提交分支。
3. 在 `submissions/mcp-hackathon/<团队>-<项目>/` 中加入五项必需材料。
4. 使用 MCP Hackathon PR 模板，向 `xagentAI/xagt-plugin:main` 发起 Pull Request。

```bash
git clone https://github.com/<你的-github-用户名>/xagt-plugin.git
cd xagt-plugin
git checkout -b submit-team-project

PROJECT_DIR="submissions/mcp-hackathon/team-project"
mkdir -p "$PROJECT_DIR/source" "$PROJECT_DIR/verification"
cp submissions/TEMPLATE.md "$PROJECT_DIR/SUBMISSION.md"
cp submissions/submission.example.json "$PROJECT_DIR/submission.json"
cp submissions/RIGHTS_TEMPLATE.md "$PROJECT_DIR/RIGHTS.md"
cp submissions/VERIFICATION_TEMPLATE.md "$PROJECT_DIR/verification/README.md"

# 填写全部占位内容，并将用于评审的完整源码复制到 source/。
git add "$PROJECT_DIR"
git commit -m "submit: team-project"
git push -u origin submit-team-project
```

构建本仓库后，也可以使用仓库版本的 CLI 生成三份核心元数据文件：

```bash
npm ci
npm run build
node dist/cli.js submit \
  --name "项目名称" \
  --slug "team-project" \
  --intro "该能力能够完成的真实任务" \
  --repo "https://github.com/you/project" \
  --api "https://api.example.com/v1" \
  --health "https://api.example.com/health" \
  --commit "<40位-git-commit>"
```

手动提交流程是正式标准。生成器不会上传源码，也不会替你创建 Pull Request。

### 提交后会发生什么

提交流程仅处理本届 `submissions/mcp-hackathon/` 下的项目，不重新处理往届活动。

| 状态 | 如何理解和处理 |
| --- | --- |
| 收件回复 | 一次英文回复确认已收到 PR。已有官方回复会保留，不会每次更新都重复留言。 |
| 自动检查 | 在 PR 的 **Checks** 页签和任务结果摘要中查看结果。缺少材料或版本不一致，需要在同一个 PR 中补正；仓库权限、代码下载或运行环境故障，由维护者处理。 |
| 源码保存 | 单独的任务会重新检查当前版本，并确认官方归档已保存。检查成功不等于归档已经完成。 |
| 人工评审 | 评审者检查参赛资格、源码完整性、可复现性、权利声明与质量。活动团队另行记录评审决定并公布最终结果。 |

**收到提交、检查成功、源码归档或为保存源码而合并，都不代表通过审核或获奖。任务报错也不等于评审淘汰。** 自动流程不会批准或合并 PR。

如果没有收到回复，或因仓库自身故障无法完成检查，请在 [Telegram 社群](https://t.me/XAgent_official)附上公开 PR 链接联系维护者。保留原 PR，不必重复提交，也不要公开密钥或其他凭证。

### 证明部署真实有效

公开健康检查接口必须返回本次评审对应的准确 Commit：

```json
{"status":"ok","commit":"<40位评审-commit>"}
```

同一 API 域名还必须提供 `/.well-known/xagent-verification.json`：

```json
{"schemaVersion":1,"slug":"team-project","commit":"<40位评审-commit>"}
```

自动验证会检查提交范围、源码包、常见密钥特征、公开 GitHub Commit、健康检查接口和部署证明。工作流使用 `main` 分支中的可信验证器，不会在有权限的 CI 中安装、导入、构建或运行参赛者源码。

自动检查会记录接口是否可访问，以及响应中报告的版本是否与声明一致。它不能独立证明线上服务确实由提交的源码构建，也不能保证源码完整或没有安全问题。可复现性、所有权、质量与参赛资格仍需人工评审。

### 保护开发者与活动的规则

- 只能提交你有权提交、部署并授权评审的代码、服务、依赖、数据和品牌材料。
- 禁止提交凭证、客户隐私数据、恶意软件、后门、盗取凭证逻辑、隐藏数据外传、滥用自动化或未披露的第三方调用。
- 抄袭、伪造部署证据、虚假所有权、购买互动、操纵身份或串通评分将直接导致淘汰。
- 在公布的评审期内保持 API 可访问。短期评审凭证只能通过指定私密渠道发送，禁止写入 Git。
- API 不可用、源码不完整、Commit 无法验证、部署不可复现或存在严重安全风险，都会阻止项目入选。
- 在合并前关闭 PR 等同于撤回。已经合并并获得奖励的项目，会按照提交的权利声明保留在官方归档中。

### 修改、归档与奖励发放

在提交期内，开发者可以继续在同一个 PR 中更新：

1. 新版本会触发新检查。保存源码的任务会独立复查当前版本，再创建官方归档；已被新版本替代或已关闭的 PR 版本会跳过。归档任务失败时，保存状态仍是未完成。
2. 旧检查结果不能用于修改后的代码。评审者检查当前准确版本，并记录所评审的 Commit。
3. 是否合并完整源码由维护者决定。为保存源码而合并，不代替评审决定，也不代表获奖。
4. 最终评审决定记录后，维护者另行核对归档与合并后的源码、复查线上证据，再发布包含源码包和完整性凭证的不可变验收 Release。
5. 只有验收材料封存并完成独立备份后，才批准发放奖励。
6. 后续升级必须提交新的 PR 和 Release，不能覆盖已获得奖励的版本。

官方保存确认完成后，删除 Fork 或外部仓库不会删除已归档的官方副本。独立备份需要另外执行，检查成功或同一 GitHub 仓库内的归档都不能代替它。完整执行规则请阅读 [`提交保留与奖励发放规则`](./docs/submission-retention-and-reward.md)。

### 项目评审方式

| 硬性门槛 | 评审内容 |
| --- | --- |
| 可调用 | API 与健康检查正常响应，文档中的真实任务可以执行。 |
| 真实且可维护 | 源码、固定 Commit、依赖和说明与线上服务一致。 |
| 可复现 | 评审者可以理解、测试并根据提交材料重新部署该能力。 |
| 可安全评审 | 不包含密钥泄露、恶意行为、严重越权或隐藏数据流。 |
| 适合 Agent | 输入、输出、错误、限制和能力边界足够清晰，可以进行 MCP 标准化。 |

评审结果分为 **通过**、**有条件通过** 或 **不接受**。只有全部硬性门槛通过后才进入评分，评审者将使用基于证据的 [`评审评分表`](./docs/review-scorecard.md)。

入选团队将进入 MCP 产品化阶段。X-Agent 会共同确定工具边界、Schema、授权、错误、限制、可观测性，以及面向 OKX 的提交材料。

## Agent 插件安装

安装插件不是本次 MCP 黑客松的必需提交条件。插件支持 Cursor、Claude Code、Codex、OpenCode 以及兼容 AgentSkills 的运行环境。

```bash
npx @xagt/agent-plugin@latest setup --target all
xagt-plugin doctor
```

需要 Node `>= 18.17`。

## 仓库开发

```bash
npm ci
npm run lint
npm test
npm run build
npm run validate:submission -- --dir submissions/mcp-hackathon/<团队>-<项目>
npm run validate:submission -- --dir submissions/mcp-hackathon/<团队>-<项目> --online
```

许可证：UNLICENSED——除非另有书面许可，仅限活动相关用途。
