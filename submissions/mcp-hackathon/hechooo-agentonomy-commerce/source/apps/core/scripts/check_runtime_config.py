from shared.config import AppConfig


def main() -> int:
    try:
        config = AppConfig.from_env()
        if not config.account_public_base_url:
            raise ValueError("public account URL is required")
        if config.clink_native_facilitator_enabled:
            config.rpc_url_for("eip155:137")
            config.rpc_url_for("eip155:8453")
    except (RuntimeError, TypeError, ValueError):
        print("Clink Core runtime configuration is invalid.")
        return 1

    print("Clink Core runtime configuration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
