# Opportunity Lens API

[English](README.md)

一个确定性、仅提供建议的机会分类 API：把一段尚未结构化的项目、产品或机制描述，转换成跨领域画像、信号成熟度、证据缺口和一个有边界的下一步验证动作。

## 你会得到什么

- 适合 Agent 工作流消费的稳定 JSON 输出。
- 覆盖 AI Agent、Crypto、Bitcoin Native、预测市场、产品商业模式、内容分发、数据基础设施和 Grant/Hackathon 等八类领域。
- 缺证据时明确返回 unknowns，不用模型语气制造确定性。
- 输出 `DATA_CHECK`、`STRATEGY_TEST`、`PRODUCT_TRIAL`、`COMMERCIAL_REVIEW` 等验证动作。
- 执行、资金、账号、通知、路由和公开发布权限全部硬编码为 `false`。
- 不访问外部 API，不存储数据，不接触钱包、签名、交易或私有系统。

## 工作方式

```text
调用方提供描述
      ↓
封闭输入校验
      ↓
确定性的关键词与证据分类
      ↓
领域画像 + 证据缺口 + 建议验证动作
```

示例输入：

```json
{
  "headline": "带时间戳市场数据的预测市场订单簿 API",
  "why_now": "公开接口刚刚上线",
  "evidence": [
    {
      "source_id": "official:docs",
      "kind": "OFFICIAL_API_DOC",
      "first_party": true
    }
  ]
}
```

响应包括 `profile`、`validation` 和 `safety`，所有可能带来真实执行影响的权限字段始终为 `false`。

## API

- `GET /health`
- `GET /.well-known/xagent-verification.json`
- `GET /openapi.json`
- `POST /v1/profile`

计划公网地址：`https://opportunity-lens-api.leolabs.me`

## 环境与隐私

- Python 3.11 及以上。
- 运行时没有第三方依赖。
- 不需要 API Key 或账号。
- 请求正文只在内存中处理，应用本身不持久化。
- 公网版本不要提交密码、私钥、个人信息、私有研究或私有 URL。
- 托管平台或反向代理可能按其自身政策保留运行元数据。

## 快速开始

```bash
git clone https://github.com/runesleo/opportunity-lens-api.git
cd opportunity-lens-api
export APP_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export APP_SLUG=runesleo-opportunity-lens
python3 app.py
```

调用示例：

```bash
curl --fail --silent \
  --request POST http://127.0.0.1:8080/v1/profile \
  --header 'content-type: application/json' \
  --data '{"headline":"面向 builder bounty 的 AI Agent API","why_now":"官方截止日期临近"}'
```

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile app.py opportunity_lens.py tests/test_api.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

## 已验证范围

本地发布门覆盖：编译、确定性分类、health 与 commit 绑定、同源 verification、封闭 OpenAPI schema、请求大小和 JSON 深度限制、超时和并发限制、安全响应头、非 root 容器配置，以及敏感信息和私有路径扫描。

独立发布审查结果见 `REVIEW-codex-pass.md`。

## v1.0.0 已知限制

- 这是确定性的关键词分类器，不是 LLM，也不负责事实核验。
- 不会抓取 URL 或判断调用方提供的证据是否真实。
- 不做应用层身份认证；公网部署必须使用边缘限流和平台资源限制。
- 标准库 HTTP 服务适合有界评审 API，不适合高吞吐多租户生产系统。
- 输出是研究辅助，不构成投资、法律、安全或财务建议。

## 路线图

- 把领域词表版本化，并加入 fixture 回归测试。
- 支持不主动抓取远端内容的签名证据引用。
- 在不持久化请求正文的前提下增加运行可观测性。
- 如果入选 X-Agent，再将能力标准化为 MCP Tool。

## 作者

由 [Leo](https://leolabs.me/?utm_source=github&utm_medium=referral&utm_content=opportunity-lens-api) 构建，关注 AI Agent、Crypto 研究、预测市场与自动化执行系统。

## 许可证

MIT，见 `LICENSE`。
