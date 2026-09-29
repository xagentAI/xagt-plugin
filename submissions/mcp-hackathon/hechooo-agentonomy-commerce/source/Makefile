PYTHON ?= python3
PYTHON_ABS := $(abspath $(shell command -v $(PYTHON) 2>/dev/null || printf '%s' "$(PYTHON)"))
WORKSPACE := $(PYTHON) scripts/clink_workspace.py
NODE := PYTHONPATH=apps/node:apps/core $(PYTHON) -m clink_node
PREDICTION_REGRESSION_SMOKES := \
	context_unit_smoke.py \
	order_preview_unit_smoke.py \
	execution_unit_smoke.py \
	polymarket_production_execution_mode_smoke.py \
	polymarket_browser_signed_order_session_smoke.py \
	polymarket_credential_store_unit_smoke.py \
	polymarket_account_binding_clob_derive_smoke.py \
	polymarket_executor_credential_store_smoke.py \
	polymarket_account_binding_unit_smoke.py \
	polymarket_deposit_wallet_service_unit_smoke.py \
	polymarket_deposit_wallet_sdk_readiness_smoke.py \
	polymarket_deposit_wallet_owner_derivation_smoke.py \
	polymarket_deposit_wallet_raw_relayer_smoke.py \
	fund_from_spending_authorization_mcp_unit_smoke.py \
	portfolio_unit_smoke.py \
	dashboard_design_smoke.py

.PHONY: doctor list test-workspace test-node test-e2e test-apps test-release test-hosted test-go test-contracts install-node \
	node-init node-start node-stop node-status node-doctor \
	core-start core-stop core-status core-test \
	marketplace-start marketplace-stop marketplace-status marketplace-test \
	prediction-markets-start prediction-markets-stop \
	prediction-markets-status prediction-markets-test \
	prediction-markets-regression

doctor:
	$(WORKSPACE) doctor

list:
	$(WORKSPACE) list

test-workspace:
	PYTHONPATH=apps/node:apps/core $(PYTHON) -m unittest discover -s tests -v

test-node:
	PYTHONPATH=apps/node:apps/core $(PYTHON) -m pytest -q apps/node/tests

test-e2e:
	PYTHONPATH=apps/node:apps/core $(PYTHON) -m unittest discover -s tests/e2e -v

test-apps:
	cd apps/core && $(PYTHON_ABS) -m pytest -q
	cd apps/marketplace && PATH="$(dir $(PYTHON_ABS)):$$PATH" $(PYTHON_ABS) -m pytest -q
	@set -e; cd apps/prediction-markets; \
	for script in $(PREDICTION_REGRESSION_SMOKES); do \
		$(PYTHON_ABS) "scripts/$$script"; \
	done

test-release:
	PYTHONPATH=apps/node:apps/core $(PYTHON_ABS) -m unittest discover -s apps/node/tests -p 'test_release*.py' -v
	# Commerce exports the runtime; private production release/deployment assets are excluded.

test-hosted:
	PYTHONPATH=apps/facilitator:apps/core:apps/node $(PYTHON_ABS) -m pytest -q apps/facilitator/tests tests/e2e/test_hosted_execution_profiles.py

test-go:
	cd packaging/linux/installer && go test ./... && go vet ./... && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o "$$(mktemp -d)/clink-installer" ./cmd/clink-installer

test-contracts:
	cd contracts && forge fmt --check && forge test -vvv

install-node:
	$(PYTHON) scripts/install_clink_node.py --profile personal

node-init:
	$(NODE) init --profile personal

node-start:
	$(NODE) start --detach

node-stop:
	$(NODE) stop

node-status:
	$(NODE) status

node-doctor:
	$(NODE) doctor

core-start:
	$(WORKSPACE) exec core start

core-stop:
	$(WORKSPACE) exec core stop

core-status:
	$(WORKSPACE) exec core status

core-test:
	$(WORKSPACE) exec core test

marketplace-start:
	$(WORKSPACE) exec marketplace start

marketplace-stop:
	$(WORKSPACE) exec marketplace stop

marketplace-status:
	$(WORKSPACE) exec marketplace status

marketplace-test:
	$(WORKSPACE) exec marketplace test

prediction-markets-start:
	$(WORKSPACE) exec prediction-markets start

prediction-markets-stop:
	$(WORKSPACE) exec prediction-markets stop

prediction-markets-status:
	$(WORKSPACE) exec prediction-markets status

prediction-markets-test:
	$(WORKSPACE) exec prediction-markets test

prediction-markets-regression:
	@set -e; cd apps/prediction-markets; \
	for script in $(PREDICTION_REGRESSION_SMOKES); do \
		$(PYTHON_ABS) "scripts/$$script"; \
	done

.PHONY: demo commerce-mcp test-commerce test-review test-submission review-api

demo:
	@$(PYTHON) -m examples.commerce.demo

commerce-mcp:
	@$(PYTHON) -m examples.commerce.node

test-commerce:
	PYTHONPATH=. $(PYTHON) -m pytest -q tests/commerce/test_core_bridge.py
	PYTHONPATH=.:apps/marketplace $(PYTHON) -m pytest -q tests/commerce/test_purchase_loop.py
	PYTHONPATH=.:apps/node:apps/core $(PYTHON) -m pytest -q tests/commerce/test_mcp_contract.py tests/commerce/test_node_transport.py tests/commerce/test_mcp_e2e.py

review-api:
	@$(PYTHON) -m agentonomy_commerce.api

test-review:
	PYTHONPATH=. $(PYTHON) -m pytest -q tests/commerce/test_core_persistence.py tests/commerce/test_review_storage.py tests/commerce/test_review_api.py tests/commerce/test_demo_sessions.py tests/commerce/test_demo_api.py tests/commerce/test_review_verifier.py
	PYTHONPATH=.:apps/marketplace $(PYTHON) -m pytest -q tests/commerce/test_review_merchant.py tests/commerce/test_review_restart.py

test-submission:
	PYTHONPATH=. $(PYTHON) -m pytest -q tests/commerce/test_submission_package.py
