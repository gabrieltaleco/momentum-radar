#!/usr/bin/env python3
"""Run a small, deterministic parameter-sensitivity study without touching live data."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import sys

try:
    from src.momentum_tool import DEFAULT_CONFIG, backtest, generate_demo_data, load_config
except ModuleNotFoundError:  # direct execution from the src directory
    from momentum_tool import DEFAULT_CONFIG, backtest, generate_demo_data, load_config


def run_sensitivity(config: dict, rows: list[dict], mode: str = "demo") -> dict:
    scenarios = []
    base_backtest = config.get("backtest", {})
    base_commission = max(0.0, float(base_backtest.get("commission_bps", 0.0)))
    base_slippage = max(0.0, float(base_backtest.get("slippage_bps", 0.0)))
    base_cost = base_commission + base_slippage
    for buy_score in (70, 75, 80, 85):
        for min_confidence in (50, 55, 60):
            for delay in (0, 1, 2):
                for total_cost_bps in (0, 6, 12):
                    variant = copy.deepcopy(config)
                    variant["thresholds"]["buy_score"] = buy_score
                    variant["thresholds"]["min_confidence"] = min_confidence
                    variant.setdefault("backtest", {})["signal_delay_days"] = delay
                    if base_cost:
                        variant["backtest"]["commission_bps"] = total_cost_bps * base_commission / base_cost
                        variant["backtest"]["slippage_bps"] = total_cost_bps * base_slippage / base_cost
                    else:
                        variant["backtest"]["commission_bps"] = total_cost_bps
                        variant["backtest"]["slippage_bps"] = 0.0
                    result = backtest(rows, variant)
                    strategy = result["strategy"]
                    benchmark = result["benchmark"]
                    active_observations = sum(1 for row in result["rows"] if row.get("selected"))
                    scenarios.append({
                        "buy_score": buy_score,
                        "min_confidence": min_confidence,
                        "signal_delay_days": delay,
                        "total_cost_bps": total_cost_bps,
                        "commission_bps": variant["backtest"]["commission_bps"],
                        "slippage_bps": variant["backtest"]["slippage_bps"],
                        "turnover": strategy["turnover"],
                        "observations": strategy["observations"],
                        "active_observations": active_observations,
                        "active_fraction": active_observations / strategy["observations"] if strategy["observations"] else 0.0,
                        "total_return": strategy["total_return"],
                        "cagr": strategy["cagr"],
                        "max_drawdown": strategy["max_drawdown"],
                        "sharpe": strategy["sharpe"],
                        "win_rate": strategy["win_rate"],
                        "benchmark_return": benchmark["total_return"],
                        "outperformed_benchmark": strategy["total_return"] > benchmark["total_return"],
                    })
    profitable = [row for row in scenarios if row["total_return"] > 0]
    outperforming = [row for row in scenarios if row["outperformed_benchmark"]]
    by_cagr = sorted(scenarios, key=lambda row: (row["cagr"], row["sharpe"]), reverse=True)
    unique_dates = sorted({str(row.get("date", "")) for row in rows if row.get("date")})
    has_benchmark = any(str(row.get("symbol", "")).upper() == "GLOBAL" for row in rows)
    required_dates = int(base_backtest.get("walk_forward_train_days", 400)) + int(base_backtest.get("walk_forward_test_days", 100))
    enough_history = len(unique_dates) >= required_dates
    if not has_benchmark:
        validation_status = "histórico sem benchmark GLOBAL; resultados não interpretáveis"
    elif not enough_history:
        validation_status = "amostra insuficiente para walk-forward"
    else:
        validation_status = "diagnóstico disponível"
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": mode,
        "scenario_count": len(scenarios),
        "warning": "Estudo de sensibilidade local; não é validação de lucro futuro nem seleção automática de parâmetros.",
        "data_window": {"dates": len(unique_dates), "first": unique_dates[0] if unique_dates else "", "last": unique_dates[-1] if unique_dates else "", "required_for_walk_forward": required_dates, "benchmark_available": has_benchmark},
        "validation_status": validation_status,
        "grid": {"buy_score": [70, 75, 80, 85], "min_confidence": [50, 55, 60], "signal_delay_days": [0, 1, 2], "total_cost_bps": [0, 6, 12]},
        "summary": {
            "profitable_fraction": len(profitable) / len(scenarios) if scenarios else 0.0,
            "outperformed_benchmark_fraction": len(outperforming) / len(scenarios) if scenarios else 0.0,
            "active_scenario_fraction": sum(1 for row in scenarios if row["active_observations"] > 0) / len(scenarios) if scenarios else 0.0,
            "median_cagr": sorted(row["cagr"] for row in scenarios)[len(scenarios) // 2] if scenarios else 0.0,
            "top_scenarios": by_cagr[:5],
        },
        "scenarios": scenarios,
    }


def write_report(result: dict, destination: Path) -> None:
    summary = result["summary"]
    lines = [
        f"# Sensibilidade de estratégia — {result.get('mode', 'local')}",
        "",
        "> [!warning] Diagnóstico, não recomendação",
        "> Os cenários abaixo servem para procurar fragilidade de parâmetros. Não são uma previsão nem uma promessa de lucro.",
        "",
        f"**Cenários:** {result['scenario_count']}",
        f"**Percentagem com retorno positivo:** {summary['profitable_fraction']:.1%}",
        f"**Percentagem acima do benchmark:** {summary['outperformed_benchmark_fraction']:.1%}",
        f"**Cenários com pelo menos uma entrada:** {summary['active_scenario_fraction']:.1%}",
        f"**CAGR mediano:** {summary['median_cagr']:.1%}",
        f"**Janela disponível:** {result.get('data_window', {}).get('dates', 0)} datas ({result.get('data_window', {}).get('first', '')} → {result.get('data_window', {}).get('last', '')})",
        f"**Validação walk-forward:** {result.get('validation_status', 'não avaliada')}",
        "",
        "## Melhores cenários por CAGR (apenas diagnóstico)",
        "",
        "| Compra | Confiança | Atraso | Custo bps | Turnover | Ativas | CAGR | Drawdown | Sharpe | Observações |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["top_scenarios"]:
        lines.append(f"| {row['buy_score']} | {row['min_confidence']} | {row['signal_delay_days']} | {row['total_cost_bps']} | {row['turnover']:.2f} | {row['active_observations']} | {row['cagr']:.1%} | {row['max_drawdown']:.1%} | {row['sharpe']:.2f} | {row['observations']} |")
    lines.extend([
        "",
        "## Como usar",
        "",
        "Se pequenas alterações no threshold ou no atraso mudarem completamente o resultado, o parâmetro está frágil. A decisão para o paper deve privilegiar a mediana e a estabilidade, não o primeiro cenário da tabela.",
    ])
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste de sensibilidade em dados demo")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CONFIG.parent / "outputs")
    parser.add_argument("--input", type=Path, default=None, help="snapshot momentum_data.json para estudar o histórico local sem rede")
    args = parser.parse_args()
    if args.input:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        config = payload.get("config", load_config(args.config))
        rows = payload.get("history", [])
        mode = f"snapshot {payload.get('meta', {}).get('as_of', '')}".strip()
    else:
        config = load_config(args.config)
        rows = generate_demo_data(config)
        mode = "dados demo"
    result = run_sensitivity(config, rows, mode)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "sensitivity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(result, args.output_dir / "sensitivity-report.md")
    print(json.dumps({"scenarios": result["scenario_count"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
