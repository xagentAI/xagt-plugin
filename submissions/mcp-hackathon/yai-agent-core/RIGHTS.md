# RIGHTS · 权利与授权声明

## 1. 提交人

- 提交团队：**YAI**（单人团队）
- 提交人 / 版权人：**Gi-Tuu**（https://github.com/Gi-Tuu）
- 项目仓库：https://github.com/Gi-Tuu/yai-agent-core
- 提交人声明：本项目全部代码、文档、示例均由本人原创编写，对代码、服务、依赖与数据拥有提交所需的全部权利；不存在未披露的第三方代码抄袭、虚假部署或身份操纵。

## 2. 项目许可证

本项目以 **MIT License** 开源，许可证全文见 `source/LICENSE`：

> Copyright (c) 2026 Gi-Tuu

任何人（含 X-Agent 评审与后续 MCP 标准化流程）可在 MIT 条款下使用、复制、修改、合并、发布、再许可与分发。

## 3. 第三方依赖许可证

内核本体（`src/yai_core/` 的核心部分）**零第三方运行时依赖**，仅使用 Python 标准库。
下列依赖全部为可选 extras（按需安装、模块内懒加载），均为 MIT / BSD / Apache 类宽松许可证，完整版本锁定见 `source/uv.lock`，各依赖的许可证原文随其分发包提供：

| 依赖（extras） | 用途 | 许可证 |
|---|---|---|
| openai（llm） | OpenAI 兼容模型客户端（线上接 DeepSeek） | Apache-2.0 |
| fastapi（server） | HTTP API 框架 | MIT |
| uvicorn[standard]（server） | ASGI 服务器 | BSD-3-Clause |
| pydantic（server） | 请求模型与数据校验 | MIT |
| starlette（fastapi 传递依赖） | ASGI 工具集 | BSD-3-Clause |
| mcp（mcp） | 官方 Model Context Protocol Python SDK v2 | MIT |
| anyio / httpx / httpcore（传递依赖） | 异步与 HTTP 运行时 | MIT / BSD-3-Clause |
| pydantic-core / typing-extensions / sniffio / h11 / idna 等 | 运行时支撑库 | MIT / BSD / PSF 类宽松许可 |

开发期工具（pytest、ruff、python-docx 等）仅用于测试与文档构建，**不进入运行时镜像与服务**。
如评审需要逐包许可证清单，可在隔离环境执行 `uv tree` / 查看 `uv.lock` 完整复现。

## 4. 数据与外部服务

- 线上服务不采集、不存储、不转发任何用户个人数据；内置示例数据（3 条演示笔记、演示天气文案）均为虚构。
- 运行时唯一的外部出站请求是发往模型 API（线上为 DeepSeek，https://api.deepseek.com）的任务推理请求，遵循该服务方的公开服务条款；提交人对发送内容负责，不包含任何第三方隐私数据。
- 不使用任何未授权的付费资源、私有数据集或抓取数据。

## 5. 提交与存档授权

提交人授权 X-Agent 官方及评审流程：

1. 在隔离评审环境中拉取、构建、运行本提交的 `source/` 与在线服务，进行硬门槛校验、源码评审、安全与数据审查；
2. 在通过评审后，将与评审基线 commit 一致的完整源码复制到官方存档 ref、生成不可变的验收 release；
3. 对入选项目按公开规则进行 MCP 标准化适配（适配器与提交包由 X-Agent 侧拥有，底层能力的真实性、运行与维护责任由提交人承担）。

提交人理解：通过评审不构成 OKX 收录、上架、流量或收益的承诺；撤回未合并 PR 即视为退赛；已验收/获奖的源码将保留在官方存档中。

## 6. 商标与署名

- "YAI Agent Core" 与 "AMBRACE（拥爱）"为提交人自有项目名称；
- DeepSeek、OKX、X-Agent、Render、GitHub 等名称归各自权利人所有，本项目仅作技术兼容性描述，不暗示任何背书或关联关系。
