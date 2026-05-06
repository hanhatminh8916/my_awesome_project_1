#!/usr/bin/env python3
"""
Simulate three service-health scenarios on EKS and collect Prometheus
metrics for ML training data.

SCENARIOS
---------
  normal    All 16 services running          → collect 10 min
  degraded  2 of 4 agent1 services scaled=0  → collect  5 min, then restore
  down      All 4 agent1 services scaled=0   → collect  5 min, then restore

PRE-REQUISITES
--------------
  1. kubectl in PATH, KUBECONFIG valid for microservices-cluster
  2. Prometheus port-forward running in a separate terminal:
       kubectl port-forward svc/prometheus -n monitoring 9090:9090

USAGE
-----
  # Full simulation (~23 min total):
  python simulate_scenarios.py

  # Only specific scenarios:
  python simulate_scenarios.py --scenarios normal,degraded

  # Custom Prometheus URL / output path:
  python simulate_scenarios.py --prom-url http://localhost:9090 --output training_data.csv

OUTPUT
------
  training_data.csv  (1 row per service per 15-second poll, auto-labelled)
  Expected rows  ≥  16 services × (10+5+5) min × 4 polls/min  =  1280 rows
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ── Scenario config ───────────────────────────────────────────────────────────
NAMESPACE_AGENT1  = "agent1"
AGENT1_ALL        = ["inventory-service", "order-service", "product-service", "revenue-service"]
DEGRADED_SUBSET   = ["inventory-service", "order-service"]      # 2 of 4

DEFAULT_PROM_URL  = "http://localhost:9090"
DEFAULT_OUTPUT    = str(Path(__file__).parent / "training_data.csv")

NORMAL_DURATION   = 10   # minutes
DEGRADED_DURATION = 5
DOWN_DURATION     = 5
COLLECT_INTERVAL  = 15   # seconds between Prometheus polls

COLLECTOR_SCRIPT  = Path(__file__).parent / "prometheus_exporter.py"


# ── kubectl helpers ───────────────────────────────────────────────────────────

def kubectl_scale(namespace: str, deployment: str, replicas: int) -> bool:
    cmd = [
        "kubectl", "scale", "deployment", deployment,
        "-n", namespace, f"--replicas={replicas}",
    ]
    print(f"  >> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [WARN] {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  [OK] {deployment} → {replicas} replica(s)")
    return True


def _ready_count(namespace: str, deployment: str) -> int:
    """Return readyReplicas for a deployment (0 if unknown)."""
    result = subprocess.run(
        ["kubectl", "get", "deployment", deployment,
         "-n", namespace, "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True,
    )
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def wait_for_scale(
    namespace: str,
    deployments: list[str],
    target_replicas: int,
    timeout_s: int = 180,
):
    """Block until all deployments reach the desired ready/unavailable state."""
    verb = "ready" if target_replicas > 0 else "terminated"
    print(f"  Waiting for {deployments} to be {verb}…", end="", flush=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        states = []
        for dep in deployments:
            ready = _ready_count(namespace, dep)
            if target_replicas == 0:
                states.append(ready == 0)
            else:
                states.append(ready >= target_replicas)
        if all(states):
            print(" ✓")
            return
        print(".", end="", flush=True)
        time.sleep(6)
    print(f"\n  [WARN] Timed out after {timeout_s}s — continuing anyway.")


# ── Collector subprocess ──────────────────────────────────────────────────────

def run_collector(
    prom_url: str,
    output: str,
    duration_min: float,
    label: str,
):
    """Invoke prometheus_exporter.py as a child process."""
    cmd = [
        sys.executable, str(COLLECTOR_SCRIPT),
        "--url",      prom_url,
        "--output",   output,
        "--interval", str(COLLECT_INTERVAL),
        "--duration", str(duration_min),
        "--label",    label,
    ]
    header = f"  SCENARIO: {label.upper()}  ({duration_min} min)"
    print(f"\n{'='*60}\n{header}\n{'='*60}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [ERROR] Collector exited {result.returncode}", file=sys.stderr)


# ── Scenario runners ──────────────────────────────────────────────────────────

def run_normal(prom_url: str, output: str):
    print("\n[scenario] NORMAL — all services running")
    run_collector(prom_url, output, NORMAL_DURATION, "normal")


def run_degraded(prom_url: str, output: str):
    print(f"\n[scenario] DEGRADED — scaling down: {DEGRADED_SUBSET}")
    for svc in DEGRADED_SUBSET:
        kubectl_scale(NAMESPACE_AGENT1, svc, 0)
    wait_for_scale(NAMESPACE_AGENT1, DEGRADED_SUBSET, 0)

    # Give Prometheus 30s to observe the services as down
    print("  Waiting 30s for Prometheus to observe 'down' state…")
    time.sleep(30)

    run_collector(prom_url, output, DEGRADED_DURATION, "degraded")

    print("\n[scenario] DEGRADED cleanup — restoring services…")
    for svc in DEGRADED_SUBSET:
        kubectl_scale(NAMESPACE_AGENT1, svc, 1)
    wait_for_scale(NAMESPACE_AGENT1, DEGRADED_SUBSET, 1)
    print("  Services restored. Sleeping 60s for metrics to settle…")
    time.sleep(60)


def run_down(prom_url: str, output: str):
    print(f"\n[scenario] DOWN — scaling down ALL agent1: {AGENT1_ALL}")
    for svc in AGENT1_ALL:
        kubectl_scale(NAMESPACE_AGENT1, svc, 0)
    wait_for_scale(NAMESPACE_AGENT1, AGENT1_ALL, 0)

    print("  Waiting 30s for Prometheus to observe 'down' state…")
    time.sleep(30)

    run_collector(prom_url, output, DOWN_DURATION, "down")

    print("\n[scenario] DOWN cleanup — restoring all agent1 services…")
    for svc in AGENT1_ALL:
        kubectl_scale(NAMESPACE_AGENT1, svc, 1)
    wait_for_scale(NAMESPACE_AGENT1, AGENT1_ALL, 1)
    print("  Services restored. Sleeping 90s for full JVM warm-up…")
    time.sleep(90)


# ── Post-run stats ────────────────────────────────────────────────────────────

def print_summary(output: str):
    try:
        import csv
        with open(output, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        total = len(rows)
        label_counts: dict[str, int] = {}
        for row in rows:
            lbl = row.get("label", "?")
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        print(f"\n{'='*60}")
        print(f"  SUMMARY: {output}")
        print(f"  Total rows   : {total}")
        for lbl, cnt in sorted(label_counts.items()):
            pct = cnt / total * 100 if total else 0
            print(f"    {lbl:<12} : {cnt:6d} rows  ({pct:.1f}%)")
        print(f"{'='*60}")
    except Exception as exc:
        print(f"  [WARN] Could not read summary: {exc}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="Simulate service scenarios and collect Prometheus metrics for ML training"
    )
    p.add_argument(
        "--prom-url", default=DEFAULT_PROM_URL,
        help=f"Prometheus base URL (default: {DEFAULT_PROM_URL})",
    )
    p.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help=f"Output CSV path (default: training_data.csv)",
    )
    p.add_argument(
        "--scenarios", default="normal,degraded,down",
        help="Comma-separated list: normal,degraded,down  (default: all three)",
    )
    return p.parse_args()


def main():
    args    = _parse_args()
    scenarios = [s.strip().lower() for s in args.scenarios.split(",")]

    # Basic validation
    valid = {"normal", "degraded", "down"}
    unknown = set(scenarios) - valid
    if unknown:
        print(f"[ERROR] Unknown scenarios: {unknown}. Valid: {valid}", file=sys.stderr)
        sys.exit(1)

    est_min = (
        (NORMAL_DURATION   if "normal"   in scenarios else 0) +
        (DEGRADED_DURATION if "degraded" in scenarios else 0) +
        (DOWN_DURATION     if "down"     in scenarios else 0) + 3   # overhead
    )

    print(f"[simulator] Scenarios : {' → '.join(s.upper() for s in scenarios)}")
    print(f"            prom_url  : {args.prom_url}")
    print(f"            output    : {args.output}")
    print(f"            estimated : ~{est_min} min total")

    if "normal"   in scenarios: run_normal(args.prom_url, args.output)
    if "degraded" in scenarios: run_degraded(args.prom_url, args.output)
    if "down"     in scenarios: run_down(args.prom_url, args.output)

    print_summary(args.output)
    print(f"\n[simulator] ✓ Complete — data saved to: {args.output}")


if __name__ == "__main__":
    main()
