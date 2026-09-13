# X-Agent AI MCP Hackathon 2026 提交清单（开放创新挑战赛）

- 官网：https://xagt.ai/hackathon?lang=zh
- 提交仓库：https://github.com/xagentAI/xagt-plugin（Fork 后提 PR）
- 关键时间：报名+开发 09.02–09.19；技术审核评审 09.20–10.01；结果 10.02–10.04

## 硬门槛（7 项最低提交要求）

1. 评审窗口内可调用的已部署 API
2. GET /health 返回 `{"status":"ok","commit":"<40位被审 commit>"}`
3. 完整源码放入 PR 的 `source/`（外链仓库不算提交）
4. 与部署一致的公开 GitHub pinned commit
5. 可复现的 setup/test/deploy/一次真实调用说明
6. `/.well-known/xagent-verification.json` → `{"schemaVersion":1,"slug":...,"commit":...}`
7. 安全/数据/依赖/权利声明（RIGHTS.md）

## 提交目录

```
submissions/mcp-hackathon/<team>-<project>/
├── SUBMISSION.md
├── submission.json
├── RIGHTS.md
├── source/
└── verification/README.md
```

## YAI 的打法

- 卖点：嵌入式自适应 Agent 内核（官方赛道明列 Agent 基础设施）
- 杀手证据：同一 Core 挂载两个宿主能力集，API 完成两类不同任务
- 不需要自建 MCP Server（官方验证后协助标准化）
- 禁止：链上安全/审计类项目

## 提交物骨架（已落地，2026-09-10 按官方 validate-submission.mjs 核对）

- 元数据目录：`submissions/mcp-hackathon/yai-agent-core/`（SUBMISSION.md / RIGHTS.md /
  verification/README.md / submission.template.json；`source/` 不入库，构建时生成）
- 构建 + 离线预检：`python scripts/build_xagent_submission.py`
  （git archive HEAD 导出 source/、注入 reviewCommit、镜像官方结构/密钥/体积校验）
- 线上一致性预检：`python scripts/build_xagent_submission.py --online`
  （校验 GitHub commit 可公开访问、/health 与验证端点的 slug/commit 三处一致）
- slug 统一定名 `yai-agent-core`（render.yaml、.env.example、验证端点、提交目录四处一致）
- 冻结提交时：Render 关 autoDeploy → 手动部署 pinned commit → 跑 --online 预检 →
  fork xagt-plugin → 复制 dist 快照目录 → 提 PR（只动一个提交目录）
- 评审期保活（2026-09-20 ~ 10-04）：`.github/workflows/keepwarm.yml` 每 10 分钟 GET /health，
  规避 Render 免费层冷启动（30–90s）撞校验器 10s GET 超时；评审结束后手动停用。
- 校验器口径（2026-09-13 复核官方 scripts/validate-submission.mjs）：10s 超时与 64KiB 上限
  只卡 health / 部署证明两个 GET；POST 不进自动门槛；包体 5MiB/文件、20MiB/包、2000 文件上限。
