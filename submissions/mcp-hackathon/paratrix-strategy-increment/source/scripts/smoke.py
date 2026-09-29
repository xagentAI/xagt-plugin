"""Run a real HTTP workflow; no credentials required. Outputs an offline evidence bundle."""

import argparse
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--output", type=Path, default=Path("runtime/smoke-evidence.json"))
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(path, body=None):
        request = urllib.request.Request(
            args.base_url.rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"User-Agent": "StrategyIncrement-Verification/1.0", **(
                {"Content-Type": "application/json"} if body is not None else {}
            )},
        )
        with opener.open(request, timeout=20) as response:
            return json.load(response)

    health = call("/health")
    cases = call("/v1/demo-cases")["cases"]
    example = call("/v1/demo-cases/" + cases[0]["id"])
    a = call("/v1/data-snapshots", {"curve": example["baseline"]})
    b = call("/v1/data-snapshots", {"curve": example["candidate"]})
    config = {
        "baseline_snapshot_id": a["snapshot_id"],
        "candidate_snapshot_id": b["snapshot_id"],
        "criteria": example["criteria"],
        "data_seen": True,
        "mode": "historical_exploration",
    }
    assert call(
        "/v1/comparison-inputs/validate",
        {k: config[k] for k in ("baseline_snapshot_id", "candidate_snapshot_id")},
    )["comparable"]
    experiment = call("/v1/experiments", config)
    evidence = call(experiment["evidence_url"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "health": health,
                "experiment_id": experiment["experiment_id"],
                "status": experiment["result"]["status"],
                "evidence": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
