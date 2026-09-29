# Bazaar 小规模供应接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将 CDP Bazaar 接入为可持续同步的候选供应源，并把 Clink Marketplace 补齐到支持 5–20 家商家正式试运营的稳定购买闭环。

**架构：** Bazaar 只负责发现，Marketplace 使用 Postgres 保存 Registry 进度、候选服务、商家认领和本地验证结果；只有 `verified` Offering 才进入 Hermes 公共目录。购买继续由 Marketplace 编排、Clink Core 控制资金与风控，Redis 只保存短期敏感输入，服务结果即时返回 Hermes 而不落明文。

**技术栈：** Python 3.11、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、Postgres 17、Redis 7、MCP、Docker Compose、pytest。

## 全局约束

- 试运营规模为 5–20 家商家，不引入 Elasticsearch、Kafka、Kubernetes 或消费者商城。
- Bazaar 数据属于不可信外部输入，不能直接继承 `verified` 状态。
- Hermes 只能访问公开 MCP，不能访问商家、管理员、Registry 同步或 Core 接口。
- Marketplace 不保存用户服务输入和服务结果明文。
- Core 是唯一授权、风控、额度、结算和审计控制面。
- 每项行为变更必须先写失败测试，再写最小实现。

---

### Task 1: 修复现有真实购买阻断项

**文件：**
- 修改：`requirements.txt`
- 修改：`services/core_gateway.py`
- 修改：`services/purchase_service.py`
- 测试：`tests/test_purchase_contracts.py`

**接口：**
- 使用：`HttpCoreGateway.evaluate_policy(payload: dict) -> dict`
- 保证：`PurchaseService.execute()` 使用 Preview 内锁定的 `payment`，而不是 Offering 的第一个支付选项。

- [ ] **步骤 1：编写失败测试**

```python
def test_core_gateway_uses_plural_policy_path():
    gateway = RecordingCoreGateway()
    gateway.evaluate_policy({"action_id": "act_1"})
    assert gateway.last_path == "/policies/evaluate"


def test_execute_rejects_when_selected_payment_drifted(repository, core):
    preview = create_preview_with_payment_index(repository, payment_index=1)
    replace_second_payment_amount(repository, "2000000")
    purchase = PurchaseService(repository, core).execute(preview.preview_id)
    assert purchase.reason_code == "QUOTE_DRIFT"


def test_execute_keeps_selected_payment_when_first_option_changes(repository, core):
    preview = create_preview_with_payment_index(repository, payment_index=1)
    replace_first_payment_amount(repository, "9000000")
    purchase = PurchaseService(repository, core).execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="fund_auth_1",
    )
    assert core.reserved_payload["amount_atomic"] == preview.payment["amount_atomic"]
```

- [ ] **步骤 2：运行测试并确认失败原因正确**

运行：`pytest -q tests/test_purchase_contracts.py`

预期：policy path 为旧的 `/policy/evaluate`，以及执行阶段错误读取 `payment_options[0]` 导致测试失败。

- [ ] **步骤 3：实现最小修复**

```python
def evaluate_policy(self, payload):
    return self._post(f"{self.policy_url}/policies/evaluate", payload)
```

执行时从 Offering 中查找与 `preview.quote_hash` 一致的支付选项：

```python
current = next(
    (
        option.model_dump(mode="json")
        for option in offering.payment_options
        if digest(option.model_dump(mode="json")) == preview.quote_hash
    ),
    None,
)
if current is None:
    return self._save(preview, pid, "failed", "QUOTE_DRIFT", now)
```

在 `requirements.txt` 中加入 `python-dotenv>=1.0,<2`。

- [ ] **步骤 4：运行测试**

运行：`pytest -q tests/test_purchase_contracts.py tests/test_final_marketplace_purchase.py`

预期：全部通过。

- [ ] **步骤 5：提交**

```bash
git add requirements.txt services/core_gateway.py services/purchase_service.py tests/test_purchase_contracts.py
git commit -m "Fix marketplace purchase contracts"
```

### Task 2: 持久化商家登录、Challenge 和 Manifest

**文件：**
- 修改：`storage/tables.py`
- 新增：`migrations/versions/20260713_0002_durable_onboarding.py`
- 修改：`services/marketplace_repository.py`
- 修改：`services/identity_service.py`
- 修改：`services/marketplace_app.py`
- 测试：`tests/test_durable_merchant_onboarding.py`

**接口：**
- 新增：`MarketplaceRepository.create_merchant_session(token_hash, wallet_address, expires_at)`
- 新增：`MarketplaceRepository.resolve_merchant_session(token) -> str | None`
- 新增：`MarketplaceRepository.save_challenge(item)` 与 `consume_challenge(nonce, purpose, subject)`
- 新增：`MarketplaceRepository.save_manifest(manifest_id, manifest, status, signer=None, signature=None)`
- 新增：`MarketplaceRepository.get_manifest(manifest_id) -> ClinkServiceManifest | None`

- [ ] **步骤 1：编写失败测试**

```python
def test_siwe_session_survives_app_recreation(database_url, signed_siwe):
    first = build_app(database_url)
    token = verify_siwe(first, signed_siwe)["access_token"]
    second = build_app(database_url)
    response = second.post(
        "/merchant/manifests",
        headers={"Authorization": f"Bearer {token}"},
        json=manifest_payload(),
    )
    assert response.status_code == 200


def test_manifest_claim_survives_app_recreation(database_url, merchant_token):
    manifest_id = submit_manifest(build_app(database_url), merchant_token)
    response = build_app(database_url).post(
        f"/merchant/manifests/{manifest_id}/claim-challenge",
        headers={"Authorization": f"Bearer {merchant_token}"},
    )
    assert response.status_code == 200
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest -q tests/test_durable_merchant_onboarding.py`

预期：重建 app 后 session 或 Manifest 不存在。

- [ ] **步骤 3：添加持久化表和 Repository 方法**

新增会话表：

```python
class MerchantSessionRow(Base):
    __tablename__ = "merchant_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(42), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Access token 只以 SHA-256 保存。`IdentityService` 改为接收 Repository，并使用 `ChallengeRow` 原子消费 nonce。`marketplace_app.py` 删除内存 `sessions` 和 `pending_manifests`。

- [ ] **步骤 4：运行迁移和测试**

运行：`alembic upgrade head`

运行：`pytest -q tests/test_durable_merchant_onboarding.py tests/test_v02_identity_manifest.py`

预期：全部通过，重复消费 nonce 返回拒绝。

- [ ] **步骤 5：提交**

```bash
git add storage/tables.py migrations/versions/20260713_0002_durable_onboarding.py services/marketplace_repository.py services/identity_service.py services/marketplace_app.py tests/test_durable_merchant_onboarding.py
git commit -m "Persist merchant onboarding state"
```

### Task 3: 实现 Bazaar 分页目录同步与断点恢复

**文件：**
- 修改：`shared/config.py`
- 修改：`.env.example`
- 修改：`adapters/cdp_bazaar.py`
- 修改：`services/marketplace_repository.py`
- 修改：`services/registry_aggregation.py`
- 测试：`tests/test_bazaar_inventory_sync.py`

**接口：**
- 新增：`CdpBazaarAdapter.fetch_page(offset: int, limit: int, etag: str | None) -> RegistryPage`
- 新增：`MarketplaceRepository.get_registry_cursor(registry_id) -> dict`
- 新增：`MarketplaceRepository.save_registry_cursor(...)`
- 新增：`RegistryAggregator.sync_registry(registry_id, max_pages=None) -> dict`

- [ ] **步骤 1：编写分页和恢复失败测试**

```python
def test_bazaar_inventory_sync_pages_until_total(repository):
    adapter = FakeBazaarAdapter(pages={0: page(0, 2, total=3), 2: page(2, 1, total=3)})
    result = RegistryAggregator(repository, {"cdp_bazaar": adapter}).sync_registry("cdp_bazaar")
    assert result == {"registry_id": "cdp_bazaar", "status": "succeeded", "count": 3, "next_offset": 0}
    assert repository.stats()["offerings"] == 3


def test_bazaar_sync_resumes_after_partial_page_failure(repository):
    adapter = FakeBazaarAdapter(fail_at=2)
    result = RegistryAggregator(repository, {"cdp_bazaar": adapter}).sync_registry("cdp_bazaar")
    assert result["status"] == "partial"
    assert repository.get_registry_cursor("cdp_bazaar")["cursor"] == "2"
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest -q tests/test_bazaar_inventory_sync.py`

预期：当前 adapter 只有 semantic search，没有分页 inventory 与持久化 cursor。

- [ ] **步骤 3：实现分页 Inventory Adapter**

```python
def fetch_page(self, *, offset=0, limit=100, etag=None):
    headers = {"If-None-Match": etag} if etag else {}
    response = self.session.get(
        self.resources_url,
        params={"type": "http", "limit": limit, "offset": offset},
        headers=headers,
        timeout=self.timeout_seconds,
    )
    if response.status_code == 304:
        return {"items": [], "offset": offset, "total": offset, "etag": etag, "not_modified": True}
    response.raise_for_status()
    payload = response.json()
    return {
        "items": payload.get("items", []),
        "offset": payload.get("pagination", {}).get("offset", offset),
        "limit": payload.get("pagination", {}).get("limit", limit),
        "total": payload.get("pagination", {}).get("total", 0),
        "etag": response.headers.get("etag"),
    }
```

配置增加 `MARKETPLACE_CDP_BAZAAR_RESOURCES_URL`、`MARKETPLACE_BAZAAR_SYNC_PAGE_SIZE=100` 和 `MARKETPLACE_BAZAAR_SYNC_MAX_PAGES=10`。

- [ ] **步骤 4：实现幂等导入与断点恢复**

导入时始终保留现有可信状态：

```python
existing = repository.get_offering(offering.offering_id)
status = existing.status if existing and existing.status in {"verified", "stale", "disabled"} else "discovered"
repository.upsert_offering(offering.model_copy(update={"status": status}))
```

每页成功后更新 offset；到达 total 后将 offset 重置为 0 并记录 `succeeded`。页面失败时保存当前 offset 和 `partial`。

- [ ] **步骤 5：运行测试**

运行：`pytest -q tests/test_bazaar_inventory_sync.py tests/test_cdp_bazaar.py`

预期：分页、恢复、去重、304 和可信状态保持测试全部通过。

- [ ] **步骤 6：提交**

```bash
git add shared/config.py .env.example adapters/cdp_bazaar.py services/marketplace_repository.py services/registry_aggregation.py tests/test_bazaar_inventory_sync.py
git commit -m "Add durable Bazaar inventory sync"
```

### Task 4: 实现候选服务池与商家一键认领

**文件：**
- 修改：`services/marketplace_repository.py`
- 修改：`services/marketplace_app.py`
- 新增：`services/candidate_service.py`
- 测试：`tests/test_bazaar_candidate_claim.py`

**接口：**
- 新增：`CandidateService.list_candidates(domain=None, pay_to=None, query=None, limit=20)`
- 新增：`CandidateService.create_manifest_draft(offering_id, wallet_address) -> ClinkServiceManifest`
- 新增接口：`GET /merchant/candidates`
- 新增接口：`POST /merchant/candidates/{offering_id}/claim-draft`

- [ ] **步骤 1：编写候选查询和冲突测试**

```python
def test_merchant_can_create_prefilled_manifest_from_bazaar_candidate(client, merchant_token, candidate):
    response = client.post(
        f"/merchant/candidates/{candidate.offering_id}/claim-draft",
        headers={"Authorization": f"Bearer {merchant_token}"},
    )
    assert response.status_code == 200
    assert response.json()["manifest"]["offerings"][0]["endpoint"] == candidate.endpoint


def test_claim_rejects_provider_owned_by_another_wallet(client, other_wallet_token, owned_candidate):
    response = client.post(
        f"/merchant/candidates/{owned_candidate.offering_id}/claim-draft",
        headers={"Authorization": f"Bearer {other_wallet_token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "provider ownership conflict"
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest -q tests/test_bazaar_candidate_claim.py`

预期：候选查询和 claim-draft 接口不存在。

- [ ] **步骤 3：实现 CandidateService 和接口**

Manifest 草稿必须复用标准模型，并保留来源：

```python
metadata = {
    **offering.metadata,
    "claim_source": "cdp_bazaar",
    "claimed_offering_id": offering.offering_id,
}
```

只有 `discovered` Offering 可以生成候选草稿；后续继续复用已有 Manifest Claim、域名验证和 endpoint 验证流程。

- [ ] **步骤 4：运行测试**

运行：`pytest -q tests/test_bazaar_candidate_claim.py tests/test_durable_merchant_onboarding.py tests/test_verification.py`

预期：全部通过。

- [ ] **步骤 5：提交**

```bash
git add services/candidate_service.py services/marketplace_repository.py services/marketplace_app.py tests/test_bazaar_candidate_claim.py
git commit -m "Add Bazaar candidate claim flow"
```

### Task 5: 即时返回服务结果并生成可重放信誉

**文件：**
- 修改：`storage/tables.py`
- 新增：`migrations/versions/20260713_0005_reputation_events.py`
- 修改：`services/marketplace_repository.py`
- 修改：`services/reputation_service.py`
- 修改：`services/purchase_service.py`
- 修改：`services/marketplace_app.py`
- 测试：`tests/test_purchase_result_and_reputation.py`

**接口：**
- 新增：`MarketplaceRepository.record_reputation_event(offering_id, event_type, purchase_id, dimensions)`
- 新增：`MarketplaceRepository.rebuild_reputation(offering_id) -> dict`
- 调整：购买执行响应为 `{"purchase": <Purchase>, "service_result": <transient result or null>}`。

- [ ] **步骤 1：编写失败测试**

```python
def test_delivered_result_is_returned_but_not_persisted(repository, purchase_service):
    result = purchase_service.execute_ready_preview()
    assert result["service_result"] == {"risk": "low"}
    stored = repository.get_purchase(result["purchase"].purchase_id)
    assert stored.output_hash is not None
    assert "service_result" not in stored.metadata


def test_purchase_outcomes_rebuild_reputation(repository):
    repository.record_reputation_event("off_1", "delivered", "purchase_1", {"delivery_success": 100})
    repository.record_reputation_event("off_1", "paid_but_undelivered", "purchase_2", {"delivery_success": 0})
    snapshot = repository.rebuild_reputation("off_1")
    assert snapshot["sample_size"] == 2
    assert snapshot["dimensions"]["delivery_success"] == 50
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest -q tests/test_purchase_result_and_reputation.py`

预期：当前执行只返回 Purchase，且没有 Reputation Event 持久化。

- [ ] **步骤 3：添加 ReputationEventRow 和重建逻辑**

```python
class ReputationEventRow(Base):
    __tablename__ = "reputation_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("offerings.offering_id"), index=True)
    purchase_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    dimensions: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

每笔购买只记录一次结果事件，使用现有 `calculate_reputation(metrics, sample_size)` 生成快照。

- [ ] **步骤 4：调整购买结果返回**

原始服务结果只保存在当前调用栈：

```python
return {"purchase": purchase, "service_result": service_result}
```

持久层只写 `output_hash`、状态、时延、receipt 和 Core 引用。

- [ ] **步骤 5：运行测试**

运行：`pytest -q tests/test_purchase_result_and_reputation.py tests/test_final_marketplace_purchase.py tests/test_mcp_surface.py`

预期：全部通过，并确认数据库 payload 不含服务结果明文。

- [ ] **步骤 6：提交**

```bash
git add storage/tables.py migrations/versions/20260713_0005_reputation_events.py services/marketplace_repository.py services/reputation_service.py services/purchase_service.py services/marketplace_app.py tests/test_purchase_result_and_reputation.py
git commit -m "Return transient results and track reputation"
```

### Task 6: 完善 Worker、健康状态和试运营指标

**文件：**
- 修改：`services/marketplace_worker.py`
- 修改：`services/marketplace_repository.py`
- 修改：`services/marketplace_app.py`
- 修改：`shared/config.py`
- 修改：`.env.example`
- 测试：`tests/test_marketplace_operations.py`

**接口：**
- 新增：`MarketplaceRepository.registry_health() -> list[dict]`
- 新增：`MarketplaceRepository.pilot_metrics() -> dict`
- 新增：`GET /livez`，只表示 Marketplace API 进程存活并固定返回 HTTP 200。
- 健康响应新增：`api`, `worker`, `registries`, `core`, `metrics`。

- [ ] **步骤 1：编写健康降级测试**

```python
def test_health_is_degraded_when_registry_is_stale(client, repository):
    repository.save_registry_cursor("cdp_bazaar", cursor="0", status="failed", last_error="timeout")
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["registries"][0]["status"] == "failed"


def test_liveness_remains_ok_when_dependencies_are_degraded(client, repository):
    repository.save_registry_cursor("cdp_bazaar", cursor="0", status="failed", last_error="timeout")
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"service": "clink_marketplace", "status": "alive"}


def test_pilot_metrics_are_reported(client, repository):
    response = client.get("/healthz")
    assert set(response.json()["metrics"]) >= {
        "candidate_offerings", "claimed_providers", "verified_offerings", "stale_offerings"
    }
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest -q tests/test_marketplace_operations.py`

预期：当前 health 只返回 worker 和简单 stats。

- [ ] **步骤 3：实现 Worker 周期**

Worker 每个同步周期按以下顺序执行：Registry 增量同步、Offering 15 分钟复验、Domain 每日复验、购买 Finalization 重试、heartbeat 更新。单个阶段失败只记录该阶段错误，不中断其他阶段。

- [ ] **步骤 4：实现健康状态与指标**

Core 连通性使用无资金副作用的 health endpoint；Registry 超过配置的新鲜度或 Worker heartbeat 过期时，整体状态返回 `degraded`，但 API 仍提供已有 verified 目录。

- [ ] **步骤 5：运行测试**

运行：`pytest -q tests/test_marketplace_operations.py tests/test_verification.py`

预期：全部通过。

- [ ] **步骤 6：提交**

```bash
git add services/marketplace_worker.py services/marketplace_repository.py services/marketplace_app.py shared/config.py .env.example tests/test_marketplace_operations.py
git commit -m "Add marketplace pilot operations health"
```

### Task 7: Docker Compose 启动完整业务服务

**文件：**
- 新增：`Dockerfile`
- 新增：`.dockerignore`
- 新增：`scripts/container-entrypoint.sh`
- 修改：`docker-compose.yml`
- 修改：`docs/operations.md`
- 测试：`scripts/container_smoke.sh`

**接口：**
- Compose 服务：`postgres`, `redis`, `migrate`, `marketplace-api`, `marketplace-worker`, `marketplace-mcp`。
- API 端口：`8050`；MCP 端口：`9050`。

- [ ] **步骤 1：编写容器 smoke 脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail
docker compose up -d --build
docker compose run --rm migrate
curl --fail --retry 30 --retry-delay 2 http://127.0.0.1:8050/livez
curl --fail --retry 30 --retry-delay 2 -I http://127.0.0.1:9050/mcp/
docker compose ps --format json | grep -q 'marketplace-worker'
```

- [ ] **步骤 2：运行脚本并确认失败**

运行：`bash scripts/container_smoke.sh`

预期：当前 Compose 只有 Postgres 和 Redis，业务服务检查失败。

- [ ] **步骤 3：实现镜像和 Compose 服务**

`Dockerfile` 使用 `python:3.11-slim`、非 root 用户和固定工作目录。`migrate` 在 API 启动前完成 `alembic upgrade head`。业务容器通过 `env_file: .env` 加载配置，并使用 Compose 内部主机名 `postgres`、`redis`、Core 服务名访问依赖。

- [ ] **步骤 4：加入健康检查和安全端口**

Postgres、Redis、API、MCP 均配置 healthcheck。Postgres 和 Redis 不暴露公网；API 和 MCP 默认绑定 `127.0.0.1`，由反向代理决定是否公开。

- [ ] **步骤 5：运行容器 smoke**

运行：`bash scripts/container_smoke.sh`

预期：migration、API、worker 和 MCP 全部正常，命令退出码为 0。

- [ ] **步骤 6：提交**

```bash
git add Dockerfile .dockerignore scripts/container-entrypoint.sh scripts/container_smoke.sh docker-compose.yml docs/operations.md
git commit -m "Containerize Clink Marketplace services"
```

### Task 8: 全链路验证与文档收敛

**文件：**
- 修改：`README.md`
- 修改：`docs/architecture.md`
- 修改：`docs/operations.md`
- 修改：`scripts/public_mcp_surface_smoke.py`
- 新增：`scripts/bazaar_pilot_smoke.py`

**接口：**
- Smoke 流程：同步 Bazaar fixture -> 查询候选 -> Claim Draft -> Manifest Claim -> Domain/402 验证 -> Hermes 搜索 -> Preview -> Core Gate -> Purchase -> 查询信誉。

- [ ] **步骤 1：编写 Bazaar pilot smoke**

Smoke 使用本地 fixture 商家和 fake Core，不访问真实资金；断言：

```python
assert sync["status"] == "succeeded"
assert candidate["status"] == "discovered"
assert verified["status"] == "verified"
assert public_search["count"] == 1
assert purchase["purchase"]["state"] == "delivered"
assert purchase["service_result"] == {"status": "ok"}
assert reputation["sample_size"] == 1
```

- [ ] **步骤 2：运行 smoke 并确认缺失行为**

运行：`python3 scripts/bazaar_pilot_smoke.py`

预期：在文档和完整编排接好前失败。

- [ ] **步骤 3：更新文档**

README 只描述最终产品，不再按 v0.1/v0.2/v0.3 路线叙述。文档明确：Bazaar 是发现源、Marketplace 是可信交易市场、Core 是控制面、Hermes 是买方 Agent。

- [ ] **步骤 4：运行全量验证**

运行：`pytest -q`

运行：`python3 scripts/bazaar_pilot_smoke.py`

运行：`python3 scripts/public_mcp_surface_smoke.py`

运行：`python3 -m compileall adapters services shared storage mcp_servers`

运行：`git diff --check`

预期：全部退出码为 0。

- [ ] **步骤 5：提交**

```bash
git add README.md docs scripts
git commit -m "Document Bazaar pilot marketplace operations"
```

## 实施完成条件

- 任务 1–8 均有独立红绿测试证据和提交。
- 全量 pytest、smoke、compileall 和容器验证通过。
- `.env`、API key、钱包私钥和用户服务输入没有进入 Git。
- `git status --short` 只包含用户原有未提交修改，或为空。
