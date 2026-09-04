#!/usr/bin/env python3
"""Validate the editable radar configuration without using network quota."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from momentum_tool import DEFAULT_CONFIG, load_config, validate_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Validar config.json sem chamadas às APIs")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        result = validate_config(load_config(args.config))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [f"não foi possível ler a configuração: {exc}"], "warnings": []}, ensure_ascii=False))
        return 2
    valid = not result["errors"]
    print(json.dumps({"valid": valid, **result, "config": str(args.config)}, ensure_ascii=False))
    for warning in result["warnings"]:
        print(f"Aviso: {warning}")
    for error in result["errors"]:
        print(f"Erro: {error}")
    return 0 if valid else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - concise CLI error
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
