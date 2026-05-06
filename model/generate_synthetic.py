"""
generate_synthetic.py
─────────────────────
Generates a realistic synthetic training dataset for Phase 5 ML anomaly detection.

Target: 32,000 rows  (16 services × 2000 timestamps)
  normal    : 16,000 rows  (16 × 1000 ticks)
  degraded  :  8,000 rows  (16 ×  500 ticks)
  down      :  8,000 rows  (16 ×  500 ticks)

Service topology modelled:
  • agent1/agent2 leaf services (inventory, order, product, revenue)
  • manager hub services (gateway, analytics, data-aggregation, alert,
      automation-action, report, master-data, ml-bridge)
  • manager services call agent services via OpenFeign →
      feign_failures spike when agent1 is degraded/down

Usage:
    python generate_synthetic.py [--output training_data.csv] [--merge] [--seed 42]

Options:
    --output PATH   Output CSV path              (default: ./training_data.csv)
    --real   PATH   Real CSV to merge with       (default: none)
    --seed   INT    Random seed                  (default: 42)
    --rows   INT    Target rows per label-tick step; controls volume (default: 2000)
"""

import argparse
import csv
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── Service catalogue ─────────────────────────────────────────────────────────
# (job_name, service_name, cluster, role)
SERVICES = [
    # agent1
    ("agent1-inventory",            "inventory",            "agent1",   "leaf"),
    ("agent1-order",                "order",                "agent1",   "leaf"),
    ("agent1-product",              "product",              "agent1",   "leaf"),
    ("agent1-revenue",              "revenue",              "agent1",   "leaf"),
    # agent2
    ("agent2-inventory",            "inventory",            "agent2",   "leaf"),
    ("agent2-order",                "order",                "agent2",   "leaf"),
    ("agent2-product",              "product",              "agent2",   "leaf"),
    ("agent2-revenue",              "revenue",              "agent2",   "leaf"),
    # manager — higher traffic hub services
    ("manager-central-api-gateway", "central-api-gateway",  "manager",  "gateway"),
    ("manager-data-aggregation",    "data-aggregation",     "manager",  "hub"),
    ("manager-central-analytics",   "central-analytics",    "manager",  "hub"),
    ("manager-alert",               "alert",                "manager",  "hub"),
    ("manager-automation-action",   "automation-action",    "manager",  "hub"),
    ("manager-report",              "report",               "manager",  "hub"),
    ("manager-master-data",         "master-data",          "manager",  "hub"),
    ("manager-ml-bridge",           "ml-bridge",            "manager",  "hub"),
]

# ── Per-role baseline traffic profiles ────────────────────────────────────────
#  Each entry: (mean_req_rate, std_req, mean_mem_mb, std_mem, mean_cpu, std_cpu)
PROFILES = {
    "gateway": (25.0, 5.0,  350, 30,  0.30, 0.08),
    "hub":     (12.0, 3.0,  280, 25,  0.20, 0.06),
    "leaf":    ( 8.0, 2.5,  240, 20,  0.18, 0.05),
}

CSV_COLUMNS = [
    "timestamp", "job", "service_name", "cluster",
    "is_down", "memory_used_bytes", "request_rate",
    "error_rate", "cpu_usage", "feign_failures", "label",
]


# ─────────────────────────────────────────────────────────────────────────────
def _clip(val: float, lo: float = 0.0, hi: float = float("inf")) -> float:
    return max(lo, min(hi, val))


def _jitter(rng, mean, std, lo=0.0, hi=float("inf")) -> float:
    return _clip(float(rng.normal(mean, std)), lo, hi)


def _snapshot(
    rng: np.random.Generator,
    ts: datetime,
    label: str,
    # which agent1 services are forced down
    agent1_down_jobs: set[str],
) -> list[dict]:
    rows = []

    # How many agent1 services are down → affects manager feign failures
    n_a1_down = len(agent1_down_jobs)
    feign_stress = n_a1_down / 4.0   # 0 … 1

    for job, svc, cluster, role in SERVICES:
        profile = PROFILES[role]
        mean_req, std_req, mean_mem_mb, std_mem_mb, mean_cpu, std_cpu = profile

        is_down = 1 if job in agent1_down_jobs else 0

        if is_down:
            # Service is completely unreachable
            memory_used_bytes = 0.0
            request_rate      = 0.0
            error_rate        = 0.0
            cpu_usage         = 0.0
            feign_failures    = 0.0
        else:
            # ── Healthy baseline with small per-service jitter ──────────────
            memory_used_bytes = _jitter(rng, mean_mem_mb * 1_000_000,
                                        std_mem_mb * 1_000_000, lo=50_000_000)

            if label == "normal":
                request_rate   = _jitter(rng, mean_req,  std_req,   lo=0)
                error_rate     = _jitter(rng, 0.002, 0.001, lo=0, hi=0.05)
                cpu_usage      = _jitter(rng, mean_cpu,  std_cpu,   lo=0.01, hi=0.95)
                feign_failures = _jitter(rng, 0.0,   0.05,  lo=0, hi=0.3)

            elif label == "degraded":
                # surviving services see more load
                stress         = 1.0 + feign_stress * 0.5
                request_rate   = _jitter(rng, mean_req * stress, std_req * 1.5, lo=0)
                error_rate     = _jitter(rng, 0.08 * (1 + feign_stress),
                                         0.03, lo=0, hi=2.0)
                cpu_usage      = _jitter(rng, mean_cpu * (1 + feign_stress * 0.6),
                                         std_cpu * 1.5, lo=0.01, hi=0.98)
                # manager services get feign failures when calling downed agent1
                if cluster == "manager":
                    feign_failures = _jitter(rng,
                                             3.5 * feign_stress, 1.0,
                                             lo=0, hi=20)
                else:
                    feign_failures = _jitter(rng, 0.05, 0.05, lo=0, hi=0.5)

            else:  # "down"
                # agent1 is fully gone; surviving services heavily stressed
                if cluster == "agent1":
                    # shouldn't reach here, but guard anyway
                    request_rate   = 0.0
                    error_rate     = 0.0
                    cpu_usage      = 0.0
                    feign_failures = 0.0
                else:
                    stress         = 1.8 if cluster == "manager" else 1.1
                    request_rate   = _jitter(rng, mean_req * stress, std_req * 2, lo=0)
                    error_rate     = _jitter(rng, 0.25, 0.08, lo=0, hi=5.0)
                    cpu_usage      = _jitter(rng, min(0.95, mean_cpu * 2.0),
                                             std_cpu * 2, lo=0.05, hi=0.99)
                    feign_failures = (_jitter(rng, 8.0, 2.0, lo=0, hi=40)
                                      if cluster == "manager" else
                                      _jitter(rng, 0.02, 0.02, lo=0))

        rows.append({
            "timestamp":         ts.isoformat(),
            "job":               job,
            "service_name":      svc,
            "cluster":           cluster,
            "is_down":           is_down,
            "memory_used_bytes": round(memory_used_bytes, 2),
            "request_rate":      round(request_rate,      6),
            "error_rate":        round(error_rate,        6),
            "cpu_usage":         round(cpu_usage,         6),
            "feign_failures":    round(feign_failures,    6),
            "label":             label,
        })

    return rows


# ── Scenario generators ───────────────────────────────────────────────────────
def _generate_normal(rng, ticks: int, t0: datetime) -> list[dict]:
    rows = []
    for i in range(ticks):
        ts = t0 + timedelta(seconds=i * 15)
        rows.extend(_snapshot(rng, ts, label="normal", agent1_down_jobs=set()))
    return rows


def _generate_degraded(rng, ticks: int, t0: datetime) -> list[dict]:
    """Randomly vary which 1-2 agent1 services are degraded each tick."""
    agent1_jobs = [j for j, *_ in SERVICES if "agent1" in j]
    rows = []
    for i in range(ticks):
        ts    = t0 + timedelta(seconds=i * 15)
        # Each tick: 1 or 2 random agent1 services are down
        n_down = rng.integers(1, 3)  # 1 or 2
        down   = set(rng.choice(agent1_jobs, size=n_down, replace=False).tolist())
        rows.extend(_snapshot(rng, ts, label="degraded", agent1_down_jobs=down))
    return rows


def _generate_down(rng, ticks: int, t0: datetime) -> list[dict]:
    """All 4 agent1 services are down every tick."""
    agent1_jobs = {j for j, *_ in SERVICES if "agent1" in j}
    rows = []
    for i in range(ticks):
        ts = t0 + timedelta(seconds=i * 15)
        rows.extend(_snapshot(rng, ts, label="down", agent1_down_jobs=agent1_jobs))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
def generate(ticks_normal: int = 1000,
             ticks_degraded: int = 500,
             ticks_down: int = 500,
             seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t0  = datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)

    print(f"[synth] Generating {ticks_normal} normal ticks   "
          f"→ {ticks_normal * 16:,} rows …")
    normal_rows = _generate_normal(rng, ticks_normal, t0)

    t1 = t0 + timedelta(seconds=ticks_normal * 15)
    print(f"[synth] Generating {ticks_degraded} degraded ticks "
          f"→ {ticks_degraded * 16:,} rows …")
    degraded_rows = _generate_degraded(rng, ticks_degraded, t1)

    t2 = t1 + timedelta(seconds=ticks_degraded * 15)
    print(f"[synth] Generating {ticks_down} down ticks      "
          f"→ {ticks_down * 16:,} rows …")
    down_rows = _generate_down(rng, ticks_down, t2)

    df = pd.DataFrame(normal_rows + degraded_rows + down_rows, columns=CSV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Phase-5 training data")
    parser.add_argument("--output", default="training_data.csv",
                        help="Output CSV file (default: training_data.csv)")
    parser.add_argument("--real",   default=None,
                        help="Path to real CSV to prepend/merge (optional)")
    parser.add_argument("--seed",   type=int, default=42, help="Random seed")
    parser.add_argument("--ticks-normal",   type=int, default=1000,
                        help="Timestamps for normal scenario   (×16 = rows)")
    parser.add_argument("--ticks-degraded", type=int, default=500,
                        help="Timestamps for degraded scenario (×16 = rows)")
    parser.add_argument("--ticks-down",     type=int, default=500,
                        help="Timestamps for down scenario     (×16 = rows)")
    args = parser.parse_args()

    df = generate(
        ticks_normal   = args.ticks_normal,
        ticks_degraded = args.ticks_degraded,
        ticks_down     = args.ticks_down,
        seed           = args.seed,
    )

    # ── Optionally merge with real collected data ─────────────────────────────
    if args.real:
        real_path = Path(args.real)
        if real_path.exists():
            real_df = pd.read_csv(real_path, parse_dates=["timestamp"])
            # Keep only rows where metrics are non-trivially healthy
            # (skip warm-up rows where is_down=1 during normal scenario)
            clean_real = real_df[
                ~((real_df["label"] == "normal") & (real_df["is_down"] == 1))
            ].copy()
            before = len(clean_real)
            df = pd.concat([df, clean_real], ignore_index=True)
            print(f"[merge] Appended {before:,} clean real rows "
                  f"(dropped warm-up is_down=1 + normal rows)")
        else:
            print(f"[warn] Real CSV not found: {real_path} — skipping merge")

    # ── Summary ───────────────────────────────────────────────────────────────
    counts = df["label"].value_counts()
    print(f"\n{'='*54}")
    print(f"  SUMMARY: {Path(args.output).resolve()}")
    print(f"  Total rows : {len(df):,}")
    for lbl in ["normal", "degraded", "down"]:
        n   = counts.get(lbl, 0)
        pct = n / len(df) * 100
        print(f"    {lbl:<10}: {n:>7,} rows  ({pct:.1f}%)")
    print(f"{'='*54}\n")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    out = Path(args.output)
    df.to_csv(out, index=False)
    print(f"[done] Saved to: {out.resolve()}")
    assert len(df) >= 30_000, f"Expected ≥30 000 rows, got {len(df)}"
    print("[ok]   Row count check passed (≥30 000)")


if __name__ == "__main__":
    main()
