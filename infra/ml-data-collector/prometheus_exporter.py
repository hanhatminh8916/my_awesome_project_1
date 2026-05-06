#!/usr/bin/env python3
"""
Prometheus metrics exporter for ML training data collection.

USAGE
-----
    # 1. Start port-forward in a separate terminal:
    #    kubectl port-forward svc/prometheus -n monitoring 9090:9090

    # 2. Collect 10 minutes of "normal" data:
    python prometheus_exporter.py --duration 10 --label normal

    # 3. Append "degraded" data to same file:
    python prometheus_exporter.py --duration 5 --label degraded --output training_data.csv

OPTIONS
-------
    --url       Prometheus base URL  (default: http://localhost:9090)
    --output    CSV output path      (default: training_data.csv)
    --interval  Seconds between polls (default: 15)
    --duration  Collection window in minutes (default: 10)
    --label     Row label: normal | degraded | down (default: normal)
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ── Job → (service_name, cluster) mapping ────────────────────────────────────
JOB_META: dict[str, tuple[str, str]] = {
    "agent1-inventory":            ("inventory",           "agent1"),
    "agent1-order":                ("order",               "agent1"),
    "agent1-revenue":              ("revenue",             "agent1"),
    "agent1-product":              ("product",             "agent1"),
    "agent2-inventory":            ("inventory",           "agent2"),
    "agent2-order":                ("order",               "agent2"),
    "agent2-revenue":              ("revenue",             "agent2"),
    "agent2-product":              ("product",             "agent2"),
    "manager-data-aggregation":    ("data-aggregation",    "manager"),
    "manager-central-analytics":   ("central-analytics",   "manager"),
    "manager-alert":               ("alert",               "manager"),
    "manager-automation-action":   ("automation-action",   "manager"),
    "manager-report":              ("report",              "manager"),
    "manager-master-data":         ("master-data",         "manager"),
    "manager-ml-bridge":           ("ml-bridge",           "manager"),
    "manager-central-api-gateway": ("central-api-gateway", "manager"),
}

JOB_PATTERN = "|".join(JOB_META.keys())   # exact-match alternation for PromQL

CSV_COLUMNS = [
    "timestamp",
    "job",
    "service_name",
    "cluster",
    "is_down",              # 1 = service unreachable (up == 0), else 0
    "memory_used_bytes",    # JVM heap used bytes
    "request_rate",         # requests / second (1-min rate)
    "error_rate",           # 5xx requests / second (1-min rate)
    "cpu_usage",            # 0.0–1.0 system CPU
    "feign_failures",       # Feign call failures per minute (custom metric Phase 2)
    "label",                # normal | degraded | down
]


# ── Prometheus helpers ────────────────────────────────────────────────────────

def _instant(prom_url: str, promql: str) -> dict[str, float]:
    """
    Execute an instant PromQL query and return {job_label: float_value}.
    Returns empty dict on any error (non-fatal — missing metric → treated as 0).
    """
    try:
        resp = requests.get(
            f"{prom_url}/api/v1/query",
            params={"query": promql},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return {}
        out: dict[str, float] = {}
        for item in data["data"]["result"]:
            job = item["metric"].get("job", "")
            if job:
                try:
                    out[job] = float(item["value"][1])
                except (ValueError, IndexError):
                    out[job] = 0.0
        return out
    except Exception as exc:
        short_q = promql[:70].replace("\n", " ")
        print(f"  [WARN] query failed ({short_q}…): {exc}", file=sys.stderr)
        return {}


def collect_snapshot(prom_url: str, label: str) -> list[dict]:
    """
    Fire all Prometheus queries and return one CSV row per known job.
    Jobs with no active time-series are still emitted with is_down=1.
    """
    ts = datetime.now(timezone.utc).isoformat()

    pat = f'job=~"{JOB_PATTERN}"'

    up_vals    = _instant(prom_url, f'up{{{pat}}}')
    mem_vals   = _instant(prom_url, f'sum by (job)(jvm_memory_used_bytes{{area="heap",{pat}}})')
    req_vals   = _instant(prom_url, f'sum by (job)(rate(http_server_requests_seconds_count{{{pat}}}[1m]))')
    err_vals   = _instant(prom_url, f'sum by (job)(rate(http_server_requests_seconds_count{{status=~"5..",{pat}}}[1m]))')
    cpu_vals   = _instant(prom_url, f'avg by (job)(system_cpu_usage{{{pat}}})')
    feign_vals = _instant(prom_url, f'sum by (job)(increase(feign_call_failures_total{{{pat}}}[1m]))')

    rows: list[dict] = []
    # Emit a row for EVERY known job — jobs absent from `up_vals` are treated as down
    for job in sorted(JOB_META.keys()):
        svc, cluster = JOB_META[job]
        up_val  = up_vals.get(job, 0.0)
        is_down = 0 if up_val >= 1.0 else 1

        rows.append({
            "timestamp":        ts,
            "job":              job,
            "service_name":     svc,
            "cluster":          cluster,
            "is_down":          is_down,
            "memory_used_bytes": int(mem_vals.get(job, 0.0)),
            "request_rate":     round(req_vals.get(job, 0.0), 6),
            "error_rate":       round(err_vals.get(job, 0.0), 6),
            "cpu_usage":        round(cpu_vals.get(job, 0.0), 6),
            "feign_failures":   round(feign_vals.get(job, 0.0), 4),
            "label":            label,
        })
    return rows


# ── Main collection loop ──────────────────────────────────────────────────────

def export(
    prom_url: str,
    output_path: str,
    interval_s: int,
    duration_min: float,
    label: str,
) -> int:
    """Collect metrics at `interval_s` cadence for `duration_min` minutes."""
    write_header = (
        not os.path.exists(output_path) or os.path.getsize(output_path) == 0
    )

    print(
        f"[collector] url={prom_url}  output={output_path}\n"
        f"            interval={interval_s}s  duration={duration_min}min  label={label}"
    )

    end_time   = time.monotonic() + duration_min * 60
    total_rows = 0

    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
            print(f"  [header written]  columns: {', '.join(CSV_COLUMNS)}")

        while time.monotonic() < end_time:
            t0   = time.monotonic()
            rows = collect_snapshot(prom_url, label)
            writer.writerows(rows)
            f.flush()
            total_rows += len(rows)

            remaining = end_time - time.monotonic()
            print(
                f"  [{datetime.now().strftime('%H:%M:%S')}]  "
                f"+{len(rows)} rows  total={total_rows}  "
                f"remaining={remaining/60:.1f}min",
                flush=True,
            )

            elapsed    = time.monotonic() - t0
            sleep_for  = max(0.0, interval_s - elapsed)
            time.sleep(sleep_for)

    print(f"[collector] Done — {total_rows} rows appended to {output_path}")
    return total_rows


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="Export Prometheus metrics to CSV for ML training"
    )
    p.add_argument("--url",      default="http://localhost:9090",
                   help="Prometheus base URL (default: http://localhost:9090)")
    p.add_argument("--output",   default="training_data.csv",
                   help="Output CSV path (default: training_data.csv)")
    p.add_argument("--interval", type=int, default=15,
                   help="Seconds between Prometheus polls (default: 15)")
    p.add_argument("--duration", type=float, default=10.0,
                   help="Collection window in minutes (default: 10)")
    p.add_argument("--label",    default="normal",
                   choices=["normal", "degraded", "down"],
                   help="Row label written to CSV (default: normal)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    export(
        prom_url     = args.url,
        output_path  = args.output,
        interval_s   = args.interval,
        duration_min = args.duration,
        label        = args.label,
    )
