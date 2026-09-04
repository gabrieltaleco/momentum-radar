#!/usr/bin/env python3
"""Probe live providers without generating orders or exposing API keys."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys

try:
    from src.momentum_tool import DEFAULT_CONFIG, fetch_live_data, load_config, quality_rows
except ModuleNotFoundError:  # direct execution from the src directory
    from momentum_tool import DEFAULT_CONFIG, fetch_live_data, load_config, quality_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Validar APIs live do radar")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CONFIG.parent / "outputs")
    parser.add_argument("--allow-missing-context", action="store_true", help="não falhar se NEWS/FRED estiverem sem chave")
    args = parser.parse_args()
    config = load_config(args.config)
    rows, provider_quality, context = fetch_live_data(config)
    quality = quality_rows(rows, config, provider_quality)
    critical_symbols = {"GLOBAL", *(item["symbol"] for item in config.get("universe", []))}
    critical = [row for row in quality if row["symbol"] in critical_symbols]
    context_rows = [row for row in quality if row["symbol"] == "NEWS" or row["symbol"] == "MACRO" or row["symbol"].startswith("FRED:")]
    critical_failures = [row for row in critical if row["status"] != "OK"]
    context_failures = [row for row in context_rows if row["status"] != "OK"]
    fred_expected = len(config.get("macro", {}).get("series", []))
    fred_ok = sum(row["status"] == "OK" for row in context_rows if row["symbol"].startswith("FRED:"))
    if fred_expected and fred_ok < fred_expected:
        context_failures.append({"symbol": "FRED", "status": "ERRO", "message": f"{fred_ok}/{fred_expected} séries OK"})
    passed = not critical_failures and (args.allow_missing_context or not context_failures)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": passed,
        "allow_missing_context": args.allow_missing_context,
        "rows": len(rows),
        "critical_failures": critical_failures,
        "context_failures": context_failures,
        "quality": quality,
        "context_summary": {"news_score_symbols": len(context.get("news_scores", {})), "macro_score": context.get("macro_score", 50.0)},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / "live-validation.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "rows": len(rows), "critical_failures": len(critical_failures), "context_failures": len(context_failures), "output": str(destination)}, ensure_ascii=False))
    if critical_failures:
        print("Falhas críticas: " + "; ".join(f"{row['symbol']} ({row['message']})" for row in critical_failures))
    if context_failures:
        print("Falhas de contexto: " + "; ".join(f"{row['symbol']} ({row['message']})" for row in context_failures))
    if passed:
        print("Validação concluída: dados críticos OK. O relatório pode ser gerado em modo live.")
    else:
        print("Validação não passou: corrigir as falhas acima antes de usar sinais live.")
    return 0 if passed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - concise CLI error
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
