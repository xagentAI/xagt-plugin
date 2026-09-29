from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.deposit_wallet_service.schemas import PreparePolymarketDepositWalletRequest  # noqa: E402
from services.deposit_wallet_service.service import PolymarketDepositWalletService  # noqa: E402
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
SERVICE = PolymarketDepositWalletService(CONFIG)
APP = FastAPI(title="Clink Prediction Markets Deposit Wallet Service")


@APP.get("/healthz")
def healthz() -> dict:
    readiness = SERVICE.check_readiness(user_id="healthcheck")
    return {
        "service": "prediction_markets_deposit_wallet_service",
        "status": "ok",
        "deposit_wallet_status": readiness.status,
        "missing": readiness.missing,
    }


@APP.get("/polymarket/deposit-wallet/readiness")
def readiness(user_id: str = Query(...), owner_wallet: str | None = Query(default=None)) -> dict:
    return SERVICE.check_readiness(user_id=user_id, owner_wallet=owner_wallet).model_dump()


@APP.post("/polymarket/deposit-wallet/prepare")
def prepare(request: PreparePolymarketDepositWalletRequest) -> dict:
    return SERVICE.prepare_deposit_wallet(request).model_dump()


def main() -> None:
    uvicorn.run(APP, host=CONFIG.deposit_wallet_host, port=CONFIG.deposit_wallet_port)


if __name__ == "__main__":
    main()
