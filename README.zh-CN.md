# X-Agent MCP 黑客松与 Agent 插件

[English](./README.md) | 简体中文 | [日本語](./README.ja.md)

> **当前活动：提交一项真实、可调用的能力。X-Agent 负责验证 API 与源码，将入选项目标准化为 MCP 工具，并协助提交至 OKX Agent 生态。**

本仓库是当前 X-Agent MCP 黑客松的官方代码提交入口，同时包含 `@xagt/agent-plugin` 安装工具。

往期活动：[X-Agent × OKX Agentic Wallet Hackathon · 2026 年 5 月](https://xagt.ai/hackathon) · [代码与提交归档](./submissions/INDEX.md)

## 当前活动：X-Agent MCP 黑客松

本次活动不设置固定赛道，也不限制语言、框架或项目类型。只要你的能力可以被 AI Agent 调用，并能完成一项真实任务，就可以提交。

报名时**不要求你提前实现 MCP**。你只需要提供一项可工作的能力、已部署 API 和完整源码。项目通过验证后，X-Agent 将与入选团队共同完成 MCP 标准化。

### 一条流程看懂活动

```text
可调用的真实能力
        ↓
通过 PR 提交已部署 API 与完整源码
        ↓
验证 API、提交版本、源码与安全性
        ↓
X-Agent 完成 MCP 标准化
        ↓
协助提交至 OKX Agent 生态
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

提交时不要求实现 MCP、Streamable HTTP、x402、EIP-3009、A2MCP 或支付 SDK。

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

只提供外部 GitHub 链接不算完整提交。用于评审的全部源码必须放在 `source/` 中。即使参赛者之后删除 Fork 或外部仓库，官方记录仍然存在。

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

自动验证通过只能证明服务可访问并且版本绑定正确，不能单独证明质量、所有权、安全性或最终入选资格，这些仍需人工评审。

### 保护开发者与活动的规则

- 只能提交你有权提交、部署并授权评审的代码、服务、依赖、数据和品牌材料。
- 禁止提交凭证、客户隐私数据、恶意软件、后门、盗取凭证逻辑、隐藏数据外传、滥用自动化或未披露的第三方调用。
- 抄袭、伪造部署证据、虚假所有权、购买互动、操纵身份或串通评分将直接导致淘汰。
- 在公布的评审期内保持 API 可访问。短期评审凭证只能通过指定私密渠道发送，禁止写入 Git。
- API 不可用、源码不完整、Commit 无法验证、部署不可复现或存在严重安全风险，都会阻止项目入选。
- 在合并前关闭 PR 等同于撤回。已经合并并获得奖励的项目，会按照提交的权利声明保留在官方归档中。

### 修改、归档与奖励发放

开发者可以继续向未合并 PR 推送修改，不需要抢着合并：

1. 每个新版本都会重新验证；每个验证成功的版本都会获得独立的官方归档引用。
2. 新推送会让此前的验证和评审上下文失效；X-Agent 只评审最新的准确版本。
3. 最终入选版本连同完整源码一起合并。
4. X-Agent 再次进行线上验证，生成完整性凭证和源码包，并发布不可变验收 Release。
5. 只有验收材料封存并完成独立备份后，才批准发放奖励。
6. 后续升级必须提交新的 PR 和 Release，不能覆盖已获得奖励的版本。

即使参赛者删除 Fork 或外部仓库，也无法删除官方副本。完整执行规则请阅读 [`提交保留与奖励发放规则`](./docs/submission-retention-and-reward.md)。

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
