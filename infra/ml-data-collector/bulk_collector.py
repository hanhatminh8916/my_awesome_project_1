"""
bulk_collector.py — Phase 5 COMPREHENSIVE real data collection
═══════════════════════════════════════════════════════════════

PHASE A — HISTORY
  Kéo toàn bộ lịch sử qua Prometheus range-query API.
  Tự động gán label dựa trên số service is_down mỗi timestamp.
  Nhanh: ~1–2 phút cho 72h (không chờ thời gian thực).

PHASE B — LIVE SCENARIOS  (30 kịch bản đầy đủ)
  Nhóm 0 — Baseline normal (trước và sau mỗi nhóm)
  Nhóm 1 — Agent1: từng service riêng lẻ (4)
  Nhóm 2 — Agent1: từng cặp (6 xếp hợp)
  Nhóm 3 — Agent1: 3 service (4 xếp hợp)
  Nhóm 4 — Agent1: full down (1)
  Nhóm 5 — Agent2: từng service riêng lẻ (4)
  Nhóm 6 — Agent2: full down (1)
  Nhóm 7 — Manager: service quan trọng down (4)
  Nhóm 8 — Cross-cluster: kịch bản kết hợp (4)
  Nhóm 9 — Recovery: thu thập trong lúc services khởi động lại (2)

  Mỗi kịch bản:
    1. kubectl scale to 0 replicas
    2. Chờ pods thực sự terminated (không chỉ sleep cố định)
    3. Thu thập data (mặc định 3 phút)
    4. kubectl scale to 1 replicas
    5. Chờ pods Ready
    6. Thu thập RECOVERY window (1 phút) với label='recovery'
    7. Sleep buffer trước scenario tiếp theo

Dự kiến:
  History   : 10 000–60 000 rows tùy cluster uptime
  Scenarios : ~25 000 rows  (30 scenarios × avg 3min × 4polls × 16 svc)
  Recovery  : ~1 920 rows phụ (sau mỗi scenario)

Cách dùng:
  python bulk_collector.py [--prom-url URL] [--output PATH]
                           [--history-hours N] [--step SECONDS]
                           [--no-history] [--no-scenarios]
                           [--scenario-min N] [--merge PATH]
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import pandas as pd

# ── Service catalogue ─────────────────────────────────────────────────────────
JOB_META = {
    "agent1-inventory":            ("inventory",            "agent1"),
    "agent1-order":                ("order",               "agent1"),
    "agent1-revenue":              ("revenue",             "agent1"),
    "agent1-product":              ("product",             "agent1"),
    "agent2-inventory":            ("inventory",           "agent2"),
    "agent2-order":                ("order",               "agent2"),
    "agent2-revenue":              ("revenue",             "agent2"),
    "agent2-product":              ("product",             "agent2"),
    "manager-central-api-gateway": ("central-api-gateway", "manager"),
    "manager-data-aggregation":    ("data-aggregation",    "manager"),
    "manager-central-analytics":   ("central-analytics",   "manager"),
    "manager-alert":               ("alert",               "manager"),
    "manager-automation-action":   ("automation-action",   "manager"),
    "manager-report":              ("report",              "manager"),
    "manager-master-data":         ("master-data",         "manager"),
    "manager-ml-bridge":           ("ml-bridge",           "manager"),
}
JOBS_RE = "|".join(JOB_META.keys())

CSV_COLS = [
    "timestamp", "job", "service_name", "cluster",
    "is_down", "memory_used_bytes", "request_rate",
    "error_rate", "cpu_usage", "feign_failures", "label",
]

# ── Scenario catalogue (30 kịch bản đầy đủ) ─────────────────────────────────
# ScenarioSpec fields:
#   name         : identifier
#   a1_down      : agent1 deployments to scale to 0
#   a2_down      : agent2 deployments to scale to 0
#   mgr_down     : manager  deployments to scale to 0
#   label        : 'normal' | 'degraded' | 'down'
#   dur_min      : collection duration in minutes
#   collect_recovery : also collect 1 min during scale-back-up with label='recovery'

from dataclasses import dataclass, field

@dataclass
class ScenarioSpec:
    name:             str
    label:            str
    dur_min:          int
    a1_down:          list = field(default_factory=list)
    a2_down:          list = field(default_factory=list)
    mgr_down:         list = field(default_factory=list)
    collect_recovery: bool = True

A1 = ["inventory-service", "order-service", "product-service", "revenue-service"]
A2 = ["inventory-service", "order-service", "product-service", "revenue-service"]

SCENARIOS: list[ScenarioSpec] = [
    # ═══════════════════════════════════════════════════════════════
    # NHÓM 0 — Baseline NORMAL  (trước khi bắt đầu)
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("0_normal_baseline",  "normal",   5),  # 5 phút steady-state

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 1 — Agent1: từng service riêng lẻ
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("1a_a1_inventory_only",  "degraded", 3, a1_down=["inventory-service"]),
    ScenarioSpec("1b_a1_order_only",      "degraded", 3, a1_down=["order-service"]),
    ScenarioSpec("1c_a1_product_only",    "degraded", 3, a1_down=["product-service"]),
    ScenarioSpec("1d_a1_revenue_only",    "degraded", 3, a1_down=["revenue-service"]),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 2 — Agent1: cặp service
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("2a_a1_inv_order",        "degraded", 3, a1_down=["inventory-service","order-service"]),
    ScenarioSpec("2b_a1_inv_product",      "degraded", 3, a1_down=["inventory-service","product-service"]),
    ScenarioSpec("2c_a1_inv_revenue",      "degraded", 3, a1_down=["inventory-service","revenue-service"]),
    ScenarioSpec("2d_a1_order_product",    "degraded", 3, a1_down=["order-service","product-service"]),
    ScenarioSpec("2e_a1_order_revenue",    "degraded", 3, a1_down=["order-service","revenue-service"]),
    ScenarioSpec("2f_a1_product_revenue",  "degraded", 3, a1_down=["product-service","revenue-service"]),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 3 — Agent1: 3 service (severe degraded)
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("3a_a1_3svc_no_revenue",  "degraded", 3,
                 a1_down=["inventory-service","order-service","product-service"]),
    ScenarioSpec("3b_a1_3svc_no_product",  "degraded", 3,
                 a1_down=["inventory-service","order-service","revenue-service"]),
    ScenarioSpec("3c_a1_3svc_no_order",    "degraded", 3,
                 a1_down=["inventory-service","product-service","revenue-service"]),
    ScenarioSpec("3d_a1_3svc_no_inventory","degraded", 3,
                 a1_down=["order-service","product-service","revenue-service"]),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 4 — Agent1: complete cluster down
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("4_a1_full_down", "down", 5, a1_down=A1),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 5 — Agent2: từng service riêng lẻ + full
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("5a_a2_inventory_only",   "degraded", 3, a2_down=["inventory-service"]),
    ScenarioSpec("5b_a2_order_only",       "degraded", 3, a2_down=["order-service"]),
    ScenarioSpec("5c_a2_product_only",     "degraded", 3, a2_down=["product-service"]),
    ScenarioSpec("5d_a2_revenue_only",     "degraded", 3, a2_down=["revenue-service"]),
    ScenarioSpec("5e_a2_inv_order",        "degraded", 3, a2_down=["inventory-service","order-service"]),
    ScenarioSpec("5f_a2_full_down",        "down",     5, a2_down=A2),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 6 — Manager: services quan trọng down
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("6a_mgr_gateway_down",   "degraded", 3,
                 mgr_down=["central-api-gateway"]),
    ScenarioSpec("6b_mgr_analytics_down", "degraded", 3,
                 mgr_down=["central-analytics-service"]),
    ScenarioSpec("6c_mgr_aggregation_down","degraded", 3,
                 mgr_down=["data-aggregation-service"]),
    ScenarioSpec("6d_mgr_alert_down",     "degraded", 3,
                 mgr_down=["alert-service"]),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 7 — Cross-cluster: kết hợp các cluster
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("7a_cross_a1inv_a2ord",  "degraded", 3,
                 a1_down=["inventory-service"], a2_down=["order-service"]),
    ScenarioSpec("7b_cross_a1pair_a2pair","degraded", 4,
                 a1_down=["inventory-service","order-service"],
                 a2_down=["product-service","revenue-service"]),
    ScenarioSpec("7c_cross_a1full_a2pair","down",     5,
                 a1_down=A1,
                 a2_down=["inventory-service","order-service"]),
    ScenarioSpec("7d_cross_both_full",    "down",     5, a1_down=A1, a2_down=A2),

    # ═══════════════════════════════════════════════════════════════
    # NHÓM 8 — Normal sau chuỗi failures (hệ thống recover steady)
    # ═══════════════════════════════════════════════════════════════
    ScenarioSpec("8_normal_post_failure", "normal", 5),
]


# ─────────────────────────────────────────────────────────────────────────────
# Phase A — History helpers
# ─────────────────────────────────────────────────────────────────────────────

def _query_range(prom_url: str, promql: str,
                 start_ts: float, end_ts: float, step: int = 15) -> dict:
    """Returns {job: {timestamp_float: value_float}} from /api/v1/query_range."""
    resp = requests.get(
        f"{prom_url}/api/v1/query_range",
        params={"query": promql, "start": start_ts, "end": end_ts, "step": f"{step}s"},
        timeout=60,
    )
    resp.raise_for_status()
    result: dict[str, dict[float, float]] = {}
    for series in resp.json()["data"]["result"]:
        job = series["metric"].get("job", "unknown")
        result[job] = {float(ts): float(v) for ts, v in series["values"]}
    return result


def _build_chunk_df(prom_url: str, start_ts: float,
                    end_ts: float, step: int) -> pd.DataFrame:
    """Pull all 6 metrics for one time chunk and return a raw (unlabeled) DataFrame."""
    jre = JOBS_RE
    is_up  = _query_range(prom_url, f'up{{job=~"{jre}"}}',
                          start_ts, end_ts, step)
    mem    = _query_range(prom_url,
                          f'sum by(job)(jvm_memory_used_bytes{{area="heap",job=~"{jre}"}})',
                          start_ts, end_ts, step)
    req    = _query_range(prom_url,
                          f'sum by(job)(rate(http_server_requests_seconds_count{{job=~"{jre}"}}[1m]))',
                          start_ts, end_ts, step)
    err    = _query_range(prom_url,
                          f'sum by(job)(rate(http_server_requests_seconds_count{{status=~"5..",job=~"{jre}"}}[1m]))',
                          start_ts, end_ts, step)
    cpu    = _query_range(prom_url,
                          f'avg by(job)(system_cpu_usage{{job=~"{jre}"}})',
                          start_ts, end_ts, step)
    feign  = _query_range(prom_url,
                          f'sum by(job)(increase(feign_call_failures_total{{job=~"{jre}"}}[1m]))',
                          start_ts, end_ts, step)

    # All unique timestamps observed in is_up (primary metric)
    all_ts: set[float] = set()
    for v in is_up.values():
        all_ts.update(v.keys())
    if not all_ts:
        return pd.DataFrame(columns=CSV_COLS)

    rows = []
    for ts in sorted(all_ts):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        for job, (svc, cluster) in JOB_META.items():
            up_val = is_up.get(job, {}).get(ts, 0.0)
            rows.append({
                "timestamp":         dt,
                "job":               job,
                "service_name":      svc,
                "cluster":           cluster,
                "is_down":           0 if up_val >= 0.5 else 1,
                "memory_used_bytes": round(mem.get(job, {}).get(ts, 0.0),   2),
                "request_rate":      round(req.get(job, {}).get(ts, 0.0),   6),
                "error_rate":        round(err.get(job, {}).get(ts, 0.0),   6),
                "cpu_usage":         round(cpu.get(job, {}).get(ts, 0.0),   6),
                "feign_failures":    round(feign.get(job, {}).get(ts, 0.0), 6),
                "label":             "__TBD__",
            })
    return pd.DataFrame(rows, columns=CSV_COLS)


def _auto_label(df: pd.DataFrame) -> pd.DataFrame:
    """Label rows by counting how many jobs are down at each timestamp."""
    down_per_ts = df.groupby("timestamp")["is_down"].sum()
    def _label(ts: str) -> str:
        n = down_per_ts.get(ts, 0)
        if n >= 4:  return "down"
        if n >= 1:  return "degraded"
        return "normal"
    df = df.copy()
    df["label"] = df["timestamp"].map(_label)
    return df


def pull_history(prom_url: str, max_hours: int = 72,
                 step: int = 15, chunk_hours: int = 2) -> pd.DataFrame:
    """
    Pull up to max_hours of Prometheus history in chunk_hours-sized pieces.
    Returns a labeled DataFrame.
    """
    now   = datetime.now(timezone.utc)
    start = now - timedelta(hours=max_hours)

    print(f"\n[history] Pulling {max_hours}h of history in {chunk_hours}h chunks "
          f"(step={step}s)")
    print(f"  From : {start.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  To   : {now.strftime('%Y-%m-%d %H:%M UTC')}")

    all_dfs: list[pd.DataFrame] = []
    chunk_start = start
    i = 0

    while chunk_start < now:
        chunk_end = min(chunk_start + timedelta(hours=chunk_hours), now)
        i += 1
        label_str = (f"  [chunk {i:02d}] "
                     f"{chunk_start.strftime('%m-%d %H:%M')} → "
                     f"{chunk_end.strftime('%H:%M')}")
        print(label_str, end=" … ")
        sys.stdout.flush()
        try:
            df_c = _build_chunk_df(
                prom_url,
                chunk_start.timestamp(), chunk_end.timestamp(), step
            )
            if df_c.empty:
                print("(no data)")
            else:
                all_dfs.append(df_c)
                print(f"{len(df_c):,} rows")
        except Exception as exc:
            print(f"ERROR — {exc}")

        chunk_start = chunk_end

    if not all_dfs:
        print("[history] No data found in this window.")
        return pd.DataFrame(columns=CSV_COLS)

    df = pd.concat(all_dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp", "job"])
    df = _auto_label(df)

    counts = df["label"].value_counts()
    total  = len(df)
    print(f"\n[history] Pulled {total:,} rows")
    for lbl in ["normal", "degraded", "down"]:
        n   = counts.get(lbl, 0)
        pct = n / total * 100 if total else 0
        print(f"  {lbl:<10}: {n:>7,}  ({pct:.1f}%)")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Phase B — Live scenario helpers
# ─────────────────────────────────────────────────────────────────────────────

def _kubectl_scale(namespace: str, deployment: str, replicas: int) -> None:
    result = subprocess.run(
        ["kubectl", "scale", "deployment", deployment,
         "-n", namespace, f"--replicas={replicas}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"      [warn] scale {deployment} n={namespace}: {result.stderr.strip()}")
    else:
        print(f"      >> {deployment:<35s} -n {namespace} → {replicas} replicas")


def _count_ready_replicas(namespace: str, deployment: str) -> int:
    r = subprocess.run(
        ["kubectl", "get", "deployment", deployment, "-n", namespace,
         "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True,
    )
    return int(r.stdout.strip() or "0")


def _wait_for_down(namespace: str, deployments: list[str],
                   timeout: int = 90) -> bool:
    """Wait until all listed deployments have 0 ready replicas."""
    if not deployments:
        return True
    print(f"      Waiting for {len(deployments)} pod(s) to terminate …", end=" ")
    sys.stdout.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(_count_ready_replicas(namespace, d) == 0 for d in deployments):
            elapsed = timeout - (deadline - time.time())
            print(f"terminated ({elapsed:.0f}s)")
            return True
        time.sleep(5)
    print("TIMEOUT (continuing anyway)")
    return False


def _wait_for_up(namespace: str, deployments: list[str],
                 target: int = 1, timeout: int = 240) -> bool:
    """Wait until all listed deployments have readyReplicas >= target."""
    if not deployments:
        return True
    print(f"      Waiting for {len(deployments)} pod(s) to be Ready …", end=" ")
    sys.stdout.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(_count_ready_replicas(namespace, d) >= target for d in deployments):
            elapsed = timeout - (deadline - time.time())
            print(f"ready ({elapsed:.0f}s)")
            return True
        time.sleep(10)
    print("TIMEOUT (continuing anyway)")
    return False


def _instant_snapshot(prom_url: str, label: str) -> list[dict]:
    """One point-in-time snapshot of all 16 services."""
    now = datetime.now(timezone.utc)
    ts  = now.timestamp()

    def _q(promql: str) -> dict[str, float]:
        try:
            r = requests.get(f"{prom_url}/api/v1/query",
                             params={"query": promql, "time": ts}, timeout=10)
            r.raise_for_status()
            return {s["metric"].get("job", "?"): float(s["value"][1])
                    for s in r.json()["data"]["result"]}
        except Exception:
            return {}

    jre   = JOBS_RE
    is_up = _q(f'up{{job=~"{jre}"}}')
    mem   = _q(f'sum by(job)(jvm_memory_used_bytes{{area="heap",job=~"{jre}"}})')
    req   = _q(f'sum by(job)(rate(http_server_requests_seconds_count{{job=~"{jre}"}}[1m]))')
    err   = _q(f'sum by(job)(rate(http_server_requests_seconds_count{{status=~"5..",job=~"{jre}"}}[1m]))')
    cpu_  = _q(f'avg by(job)(system_cpu_usage{{job=~"{jre}"}})')
    feign = _q(f'sum by(job)(increase(feign_call_failures_total{{job=~"{jre}"}}[1m]))')

    dt   = now.isoformat()
    rows = []
    for job, (svc, cluster) in JOB_META.items():
        up_val = is_up.get(job, 0.0)
        rows.append({
            "timestamp":         dt,
            "job":               job,
            "service_name":      svc,
            "cluster":           cluster,
            "is_down":           0 if up_val >= 0.5 else 1,
            "memory_used_bytes": round(mem.get(job,   0.0), 2),
            "request_rate":      round(req.get(job,   0.0), 6),
            "error_rate":        round(err.get(job,   0.0), 6),
            "cpu_usage":         round(cpu_.get(job,  0.0), 6),
            "feign_failures":    round(feign.get(job, 0.0), 6),
            "label":             label,
        })
    return rows


def _collect_window(prom_url: str, label: str,
                    duration_min: int, interval_s: int = 15) -> list[dict]:
    """Collect snapshots every interval_s for duration_min minutes."""
    ticks = duration_min * (60 // interval_s)
    all_rows: list[dict] = []
    for i in range(ticks):
        all_rows.extend(_instant_snapshot(prom_url, label))
        remaining = (ticks - i - 1) * interval_s / 60
        print(f"\r      [{label}] {i+1}/{ticks} ticks  "
              f"({len(all_rows):,} rows, {remaining:.1f} min left)    ", end="")
        sys.stdout.flush()
        if i < ticks - 1:
            time.sleep(interval_s)
    print()  # newline after \r
    return all_rows


def _append_csv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    out = Path(path)
    df  = pd.DataFrame(rows, columns=CSV_COLS)
    df.to_csv(out, mode="a", header=not out.exists(), index=False)


def run_scenario(prom_url: str, spec: ScenarioSpec, output_path: str,
                 scenario_min_override: int = 0) -> int:
    """
    Execute one ScenarioSpec:
      1. Scale down specified deployments
      2. Wait for pods to actually terminate (real check, not just sleep)
      3. Collect 'label' window
      4. Scale up / wait Ready
      5. Collect 'recovery' window (1 min)
      6. Short inter-scenario buffer
    Returns total rows written.
    """
    dur = scenario_min_override if scenario_min_override > 0 else spec.dur_min
    print(f"\n{'═'*65}")
    print(f"  SCENARIO: {spec.name}")
    print(f"  Label   : {spec.label}   Duration: {dur} min"
          f"   Recovery: {'yes' if spec.collect_recovery else 'no'}")
    if spec.a1_down:   print(f"  a1↓     : {spec.a1_down}")
    if spec.a2_down:   print(f"  a2↓     : {spec.a2_down}")
    if spec.mgr_down:  print(f"  mgr↓    : {spec.mgr_down}")
    print()

    total_rows = 0

    # ── Nothing to scale down (normal scenario) ──────────────────
    if not spec.a1_down and not spec.a2_down and not spec.mgr_down:
        rows = _collect_window(prom_url, spec.label, dur)
        _append_csv(rows, output_path)
        print(f"  +{len(rows):,} rows written")
        return len(rows)

    # ── Scale DOWN ────────────────────────────────────────────────
    print("  [scale-down]")
    for dep in spec.a1_down:
        _kubectl_scale("agent1", dep, 0)
    for dep in spec.a2_down:
        _kubectl_scale("agent2", dep, 0)
    for dep in spec.mgr_down:
        _kubectl_scale("manager", dep, 0)

    # Wait for actual termination (real check, not hardcoded sleep)
    if spec.a1_down:  _wait_for_down("agent1",  spec.a1_down)
    if spec.a2_down:  _wait_for_down("agent2",  spec.a2_down)
    if spec.mgr_down: _wait_for_down("manager", spec.mgr_down)

    # Extra 15s for Prometheus to reflect is_down=1 in metrics
    print("      Extra 15s Prometheus settle …", end=" ")
    sys.stdout.flush()
    time.sleep(15)
    print("ok")

    # ── Collect scenario window ───────────────────────────────────
    print(f"  [collect — {spec.label}]")
    rows = _collect_window(prom_url, spec.label, dur)
    _append_csv(rows, output_path)
    total_rows += len(rows)
    print(f"  +{len(rows):,} rows written  (label={spec.label})")

    # ── Scale UP (restore) ────────────────────────────────────────
    print("\n  [scale-up / restore]")
    for dep in spec.a1_down:
        _kubectl_scale("agent1", dep, 1)
    for dep in spec.a2_down:
        _kubectl_scale("agent2", dep, 1)
    for dep in spec.mgr_down:
        _kubectl_scale("manager", dep, 1)

    if spec.a1_down:  _wait_for_up("agent1",  spec.a1_down)
    if spec.a2_down:  _wait_for_up("agent2",  spec.a2_down)
    if spec.mgr_down: _wait_for_up("manager", spec.mgr_down)

    # ── Collect RECOVERY window ───────────────────────────────────
    if spec.collect_recovery:
        print("  [collect — recovery  (1 min during JVM warm-up)]")
        rec_rows = _collect_window(prom_url, "recovery", 1)
        _append_csv(rec_rows, output_path)
        total_rows += len(rec_rows)
        print(f"  +{len(rec_rows):,} rows written  (label=recovery)")

    # ── Buffer before next scenario ───────────────────────────────
    print("  [buffer 30s before next scenario]", end=" ")
    sys.stdout.flush()
    time.sleep(30)
    print("ok")

    return total_rows


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry-point
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(path: str) -> None:
    out = Path(path)
    if not out.exists():
        print("[summary] Output file not found.")
        return
    df = pd.read_csv(out, usecols=["label"])
    total = len(df)
    counts = df["label"].value_counts()
    print(f"\n{'='*60}")
    print(f"  FINAL SUMMARY: {out.resolve()}")
    print(f"  Total rows   : {total:,}")
    for lbl in ["normal", "degraded", "down", "recovery"]:
        n   = counts.get(lbl, 0)
        pct = n / total * 100 if total else 0
        print(f"    {lbl:<10}: {n:>8,}  ({pct:.1f}%)")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5 — Bulk Prometheus data collector (history + live scenarios)"
    )
    parser.add_argument("--prom-url",        default="http://localhost:9090",
                        help="Prometheus URL (default: http://localhost:9090)")
    parser.add_argument("--output",          default="bulk_training_data.csv",
                        help="Output CSV (default: bulk_training_data.csv)")
    parser.add_argument("--history-hours",   type=int, default=72,
                        help="Hours of history to pull (default: 72)")
    parser.add_argument("--step",            type=int, default=15,
                        help="Scrape resolution in seconds (default: 15)")
    parser.add_argument("--chunk-hours",     type=int, default=2,
                        help="Chunk size for range queries in hours (default: 2)")
    parser.add_argument("--no-history",      action="store_true",
                        help="Skip Phase A (history pull)")
    parser.add_argument("--no-scenarios",    action="store_true",
                        help="Skip Phase B (live scenarios)")
    parser.add_argument("--scenario-min",    type=int, default=3,
                        help="Base duration (minutes) per scenario (default: 3)")
    parser.add_argument("--merge",           default=None, metavar="PATH",
                        help="Append output into this existing CSV at the end")
    args = parser.parse_args()

    out_path = args.output
    out      = Path(out_path)

    # ── Phase A: History ──────────────────────────────────────────────────────
    if not args.no_history:
        df_hist = pull_history(
            prom_url    = args.prom_url,
            max_hours   = args.history_hours,
            step        = args.step,
            chunk_hours = args.chunk_hours,
        )
        if not df_hist.empty:
            df_hist.to_csv(out, index=False)
            print(f"\n[history] Written {len(df_hist):,} rows → {out.name}")
        else:
            print("[history] No historical rows to save.")

    # ── Phase B: Live scenarios ───────────────────────────────────────────────
    if not args.no_scenarios:
        print(f"\n[scenarios] Running {len(SCENARIOS)} scenarios …")
        total_scenario_rows = 0
        for i, spec in enumerate(SCENARIOS, 1):
            print(f"\n[{i}/{len(SCENARIOS)}]", end="")
            # Allow CLI override: if --scenario-min is provided and differs from
            # the spec's nominal duration, use it (but keep DOWN/normal at spec value)
            override = args.scenario_min if args.scenario_min != 3 else 0
            n = run_scenario(
                prom_url          = args.prom_url,
                spec              = spec,
                output_path       = out_path,
                scenario_min_override = override,
            )
            total_scenario_rows += n
        print(f"\n[scenarios] {total_scenario_rows:,} rows from {len(SCENARIOS)} scenarios")

    # ── Optional merge ────────────────────────────────────────────────────────
    if args.merge and Path(args.merge).exists() and out.exists():
        existing = pd.read_csv(args.merge)
        new_data = pd.read_csv(out)
        merged   = pd.concat([existing, new_data], ignore_index=True)
        merged.to_csv(args.merge, index=False)
        print(f"\n[merge] Combined {len(existing):,} + {len(new_data):,} "
              f"= {len(merged):,} rows → {args.merge}")
        out.unlink()  # remove intermediate file

    _print_summary(args.merge if (args.merge and Path(args.merge).exists()) else out_path)


if __name__ == "__main__":
    main()
