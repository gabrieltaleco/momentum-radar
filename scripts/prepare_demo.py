#!/usr/bin/env python3
"""Create the safe, reproducible fixture used by the hosted demo build.

This script refuses to replace a non-empty local portfolio unless the Render
build flag is present. It never reads an import, statement, cache, or secret.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

DEMO_POSITIONS = [
    {"symbol": "GOLD", "quantity": 10.0, "avg_cost": 180.0, "currency": "USD"},
    {"symbol": "AI", "quantity": 8.0, "avg_cost": 100.0, "currency": "USD"},
    {"symbol": "BTC", "quantity": 0.25, "avg_cost": 50000.0, "currency": "USD"},
    {"symbol": "ENERGY", "quantity": 12.0, "avg_cost": 90.0, "currency": "USD"},
]


def write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_portfolio() -> None:
    destination = ROOT / "data" / "user_portfolio.json"
    if destination.is_file():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Não substituo a carteira: ficheiro inválido ({exc}).") from exc
        if isinstance(existing, dict) and existing.get("positions") and existing.get("mode") != "demo_fixture":
            raise SystemExit("Carteira local já contém posições; preparação demo recusada.")
    write_json_atomic(
        destination,
        {
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mode": "demo_fixture",
            "positions": DEMO_POSITIONS,
        },
    )


def run_paper(output_dir: Path, prefix: str, policy: str) -> None:
    command = [
        sys.executable,
        "-m",
        "src.paper_trading",
        "--signals",
        str(output_dir / "momentum_data.json"),
        "--state",
        str(output_dir / f"{prefix}.json"),
        "--output-dir",
        str(output_dir),
        "--initial-cash",
        "100000",
        "--output-prefix",
        prefix,
        "--policy",
        policy,
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def run_sensitivity(output_dir: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "src.sensitivity",
            "--input",
            str(output_dir / "momentum_data.json"),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Preparar fixtures demo sem dados pessoais")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument("--allow-local", action="store_true", help="permitir execução manual consciente")
    args = parser.parse_args()
    if os.environ.get("RADAR_DEMO_BUILD") != "1" and not args.allow_local:
        raise SystemExit("Define RADAR_DEMO_BUILD=1 (Render) ou usa --allow-local para preparar a demo.")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prepare_portfolio()
    run_sensitivity(output_dir)
    run_paper(output_dir, "paper-week-100k", "strict")
    run_paper(output_dir, "paper-ladder-v1", "ladder")
    run_paper(output_dir, "paper-matrix-v2", "matrix")
    print(json.dumps({"demo": True, "portfolio_positions": len(DEMO_POSITIONS), "paper_ledgers": 3}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
