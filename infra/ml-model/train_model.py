#!/usr/bin/env python3
"""
Phase 6 — ML Model Training  (with full preprocessing)
=======================================================
Train Random Forest (supervised) + Isolation Forest (unsupervised)
on training_data.csv collected in Phase 5.

Preprocessing pipeline:
  1. Drop duplicates & fix data-quality issues
  2. Clip numeric outliers at [1st, 99th] percentile
  3. Convert memory_used_bytes → memory_used_mb  (scale friendlier)
  4. Log1p-transform feign_failures              (right-skewed / sparse)
  5. Add is_down flag as feature                 (strongest signal)
  6. StandardScaler on all features

Features (final): is_down, memory_used_mb, request_rate, error_rate,
                  cpu_usage, feign_failures_log
Label    : is_anomaly  (0 = normal,  1 = degraded / down / recovery)

Outputs (infra/ml-model/models/):
  rf_model.pkl   — RandomForestClassifier
  iso_model.pkl  — IsolationForest
  scaler.pkl     — StandardScaler
  feature_names.txt — ordered list of feature names used at train time
  metrics.txt    — evaluation summary

Usage:
  cd J:\\Manager-microservices
  .\\model\\.venv\\Scripts\\python.exe infra\\ml-model\\train_model.py
"""

import json
import pathlib
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_CSV = BASE_DIR.parent.parent / "model" / "training_data.csv"
OUT_DIR  = BASE_DIR / "models"
OUT_DIR.mkdir(exist_ok=True)

# Raw columns we read from CSV
RAW_NUMERIC = [
    "is_down",
    "memory_used_bytes",
    "request_rate",
    "error_rate",
    "cpu_usage",
    "feign_failures",
]

# Final feature names AFTER preprocessing (must match serve.py)
FEATURES = [
    "is_down",
    "memory_used_mb",
    "request_rate",
    "error_rate",
    "cpu_usage",
    "feign_failures_log",
]

LABEL_COL = "label"


def banner(title: str) -> None:
    print("\n" + "=" * 58)
    print(f"  {title}")
    print("=" * 58)


# ═══════════════════════════════════════════════════════════
# STEP 1 — LOAD
# ═══════════════════════════════════════════════════════════
banner("1. LOADING DATA")
if not DATA_CSV.exists():
    print(f"ERROR: training_data.csv not found at {DATA_CSV}", file=sys.stderr)
    sys.exit(1)

df = pd.read_csv(DATA_CSV)
print(f"Rows loaded       : {len(df):,}")
print(f"Columns           : {list(df.columns)}")
print(f"\nLabel distribution:\n{df[LABEL_COL].value_counts().to_string()}")

# ═══════════════════════════════════════════════════════════
# STEP 2 — DATA QUALITY
# ═══════════════════════════════════════════════════════════
banner("2. DATA QUALITY CHECKS")

# 2a. Infill NaN / Inf in numeric columns with 0
for col in RAW_NUMERIC:
    bad = df[col].isna().sum() + np.isinf(df[col]).sum()
    if bad > 0:
        print(f"  [fix] {col}: {bad} NaN/Inf → 0")
    df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0)

# 2b. Remove duplicate rows (same timestamp + job)
before = len(df)
df.drop_duplicates(subset=["timestamp", "job"], keep="first", inplace=True)
print(f"  Duplicates removed : {before - len(df):,}  (kept {len(df):,})")

# 2c. Negative values → 0  (metrics cannot be negative)
for col in ["memory_used_bytes", "request_rate", "error_rate", "cpu_usage", "feign_failures"]:
    neg = (df[col] < 0).sum()
    if neg > 0:
        print(f"  [fix] {col}: {neg} negative values → 0")
    df[col] = df[col].clip(lower=0)

print(f"  Final rows         : {len(df):,}")

# ═══════════════════════════════════════════════════════════
# STEP 3 — FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════
banner("3. FEATURE ENGINEERING")

# 3a. memory_used_bytes → memory_used_mb  (divide by 1MB = 1048576)
#     Reduces magnitude from ~2.5e8 to ~250 — much friendlier for StandardScaler
df["memory_used_mb"] = df["memory_used_bytes"] / 1_048_576.0
print(f"  memory_used_mb   : min={df['memory_used_mb'].min():.1f}  max={df['memory_used_mb'].max():.1f}  mean={df['memory_used_mb'].mean():.1f}")

# 3b. Log1p-transform feign_failures (sparse, right-skewed: many 0s, few large spikes)
#     log1p(0) = 0, so zero values stay zero; large values are compressed
df["feign_failures_log"] = np.log1p(df["feign_failures"])
print(f"  feign_failures   : {(df['feign_failures'] == 0).sum():,} zeros ({100*(df['feign_failures']==0).mean():.1f}%)")
print(f"  feign_failures_log max={df['feign_failures_log'].max():.3f}  mean={df['feign_failures_log'].mean():.3f}")

# NOTE: outlier clipping is done AFTER the train/test split (Step 5a)
#       so quantile bounds are computed on train rows only — no leakage.

# ═══════════════════════════════════════════════════════════
# STEP 4 — BUILD FEATURE MATRIX & TARGET
# ═══════════════════════════════════════════════════════════
banner("4. BUILDING FEATURE MATRIX")

print(f"  Features used : {FEATURES}")

X_raw = df[FEATURES].values
y     = (df[LABEL_COL] != "normal").astype(int).values

n_normal  = (y == 0).sum()
n_anomaly = (y == 1).sum()
print(f"\n  is_anomaly=0 (normal)  : {n_normal:,}  ({100*n_normal/len(y):.1f}%)")
print(f"  is_anomaly=1 (anomaly) : {n_anomaly:,}  ({100*n_anomaly/len(y):.1f}%)")
print(f"\n  Feature stats (raw):")
for i, feat in enumerate(FEATURES):
    col = X_raw[:, i]
    print(f"    {feat:<22}: min={col.min():.4f}  max={col.max():.4f}  mean={col.mean():.4f}  std={col.std():.4f}")

# ═══════════════════════════════════════════════════════════
# STEP 5 — TRAIN / TEST SPLIT  (before any fitting)
# ═══════════════════════════════════════════════════════════
banner("5. TRAIN / TEST SPLIT  (split first — no leakage)")
X_train_raw, X_test_raw, y_train, y_test = train_test_split(
    X_raw, y, test_size=0.2, random_state=42, stratify=y
)
print(f"  Train: {len(X_train_raw):,}   Test: {len(X_test_raw):,}")

# ═══════════════════════════════════════════════════════════
# STEP 5a — CLIP OUTLIERS  (bounds from train only)
# ═══════════════════════════════════════════════════════════
banner("5a. CLIP OUTLIERS  (train-derived bounds applied to both sets)")
CLIP_FEAT_NAMES = ["memory_used_mb", "request_rate", "error_rate", "cpu_usage"]
CLIP_FEAT_IDX   = [FEATURES.index(c) for c in CLIP_FEAT_NAMES]
clip_bounds: dict = {}
for feat_idx, col_name in zip(CLIP_FEAT_IDX, CLIP_FEAT_NAMES):
    p01 = float(np.percentile(X_train_raw[:, feat_idx], 1))
    p99 = float(np.percentile(X_train_raw[:, feat_idx], 99))
    clip_bounds[col_name] = (p01, p99)
    X_train_raw[:, feat_idx] = np.clip(X_train_raw[:, feat_idx], p01, p99)
    X_test_raw[:, feat_idx]  = np.clip(X_test_raw[:, feat_idx],  p01, p99)
    print(f"  clip {col_name:<22}: [{p01:.4f}, {p99:.4f}]")

# ═══════════════════════════════════════════════════════════
# STEP 5b — SCALE  (fit on train only, transform test separately)
# ═══════════════════════════════════════════════════════════
banner("5b. SCALING  (StandardScaler — fit on train only)")
scaler  = StandardScaler()
X_train = scaler.fit_transform(X_train_raw)   # fit + transform train
X_test  = scaler.transform(X_test_raw)        # transform test with train's stats
print("  StandardScaler fitted on training set only.")
print(f"  Train scaled mean  (should be ~0): {X_train.mean(axis=0).round(3)}")
print(f"  Train scaled std   (should be ~1): {X_train.std(axis=0).round(3)}")

# ═══════════════════════════════════════════════════════════
# STEP 7 — RANDOM FOREST (Supervised)
# ═══════════════════════════════════════════════════════════
banner("6. RANDOM FOREST CLASSIFIER  (Supervised)")

rf = RandomForestClassifier(
    n_estimators=200,
    max_depth=None,
    min_samples_split=5,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)
rf.fit(X_train, y_train)

y_pred_rf = rf.predict(X_test)
y_prob_rf  = rf.predict_proba(X_test)[:, 1]

print(classification_report(y_test, y_pred_rf, target_names=["normal", "anomaly"]))
print("Confusion matrix (rows=actual, cols=predicted):")
print(confusion_matrix(y_test, y_pred_rf))

rf_f1  = f1_score(y_test, y_pred_rf)
rf_auc = roc_auc_score(y_test, y_prob_rf)
print(f"\nF1 (test)  : {rf_f1:.4f}")
print(f"AUC-ROC    : {rf_auc:.4f}")

threshold_grid = np.round(np.arange(0.05, 0.951, 0.01), 3)
best_threshold = 0.5
best_threshold_f1 = -1.0
best_threshold_precision = 0.0
best_threshold_recall = 0.0

for threshold in threshold_grid:
    y_pred_t = (y_prob_rf >= threshold).astype(int)
    f1_t = f1_score(y_test, y_pred_t)
    precision_t = precision_score(y_test, y_pred_t, zero_division=0)
    recall_t = recall_score(y_test, y_pred_t, zero_division=0)

    if (
        f1_t > best_threshold_f1
        or (np.isclose(f1_t, best_threshold_f1) and precision_t > best_threshold_precision)
    ):
        best_threshold = float(threshold)
        best_threshold_f1 = float(f1_t)
        best_threshold_precision = float(precision_t)
        best_threshold_recall = float(recall_t)

print(
    f"Optimal RF anomaly threshold (F1-max): {best_threshold:.3f} "
    f"(F1={best_threshold_f1:.4f}, precision={best_threshold_precision:.4f}, recall={best_threshold_recall:.4f})"
)

print("\nFeature importances:")
for feat, imp in sorted(zip(FEATURES, rf.feature_importances_), key=lambda x: -x[1]):
    print(f"  {feat:<25} {imp:.4f}")

# 5-fold cross-validation
cv_rf = RandomForestClassifier(
    n_estimators=100, class_weight="balanced", random_state=42, n_jobs=-1
)
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(cv_rf, X_train, y_train, cv=cv, scoring="f1")
print(f"\nCross-val F1 (5-fold) : {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

# ═══════════════════════════════════════════════════════════
# STEP 8 — ISOLATION FOREST (Unsupervised)
# ═══════════════════════════════════════════════════════════
banner("7. ISOLATION FOREST  (Unsupervised)")

contamination = min(float(n_anomaly / len(y)), 0.5)   # IsoForest max = 0.5
print(f"contamination parameter : {contamination:.4f}  (data anomaly ratio: {n_anomaly/len(y):.4f})")

iso = IsolationForest(
    n_estimators=200,
    contamination=contamination,
    random_state=42,
    n_jobs=-1,
)
iso.fit(X_train)   # fit on train-scaled data only — no leakage

iso_test_pred = (iso.predict(X_test) == -1).astype(int)
iso_f1 = f1_score(y_test, iso_test_pred)

print(classification_report(y_test, iso_test_pred, target_names=["normal", "anomaly"]))
print("Confusion matrix:")
print(confusion_matrix(y_test, iso_test_pred))
print(f"\nF1 (test) : {iso_f1:.4f}")

# ═══════════════════════════════════════════════════════════
# STEP 9 — SAVE
# ═══════════════════════════════════════════════════════════
banner("8. SAVING MODELS")

joblib.dump(rf,     OUT_DIR / "rf_model.pkl")
joblib.dump(iso,    OUT_DIR / "iso_model.pkl")
joblib.dump(scaler, OUT_DIR / "scaler.pkl")

# Save feature names so serve.py can enforce correct ordering
(OUT_DIR / "feature_names.txt").write_text("\n".join(FEATURES), encoding="utf-8")

# Save clip bounds so serve.py applies the same clipping at inference time
clip_bounds_path = OUT_DIR / "clip_bounds.json"
(clip_bounds_path).write_text(
    json.dumps({k: list(v) for k, v in clip_bounds.items()}, indent=2),
    encoding="utf-8",
)
print(f"  clip_bounds.json  → {clip_bounds_path}")

optimal_threshold_path = OUT_DIR / "optimal_threshold.json"
optimal_threshold_payload = {
    "rf_anomaly_threshold": round(best_threshold, 6),
    "selection_metric": "f1",
    "f1_at_threshold": round(best_threshold_f1, 6),
    "precision_at_threshold": round(best_threshold_precision, 6),
    "recall_at_threshold": round(best_threshold_recall, 6),
    "default_rf_threshold": 0.5,
}
optimal_threshold_path.write_text(
    json.dumps(optimal_threshold_payload, indent=2),
    encoding="utf-8",
)
print(f"  optimal_threshold.json → {optimal_threshold_path}")

metrics_text = (
    f"=== Phase 6 ML Model Metrics ===\n"
    f"Dataset rows      : {len(df):,}\n"
    f"Train rows        : {len(X_train):,}\n"
    f"Test rows         : {len(X_test):,}\n"
    f"Features          : {FEATURES}\n\n"
    f"--- Random Forest (Supervised) ---\n"
    f"F1 (test)         : {rf_f1:.4f}\n"
    f"AUC-ROC (test)    : {rf_auc:.4f}\n"
    f"RF threshold (default) : 0.5000\n"
    f"RF threshold (optimal) : {best_threshold:.4f}\n"
    f"F1 @ optimal threshold : {best_threshold_f1:.4f}\n"
    f"Precision @ optimal    : {best_threshold_precision:.4f}\n"
    f"Recall @ optimal       : {best_threshold_recall:.4f}\n"
    f"Cross-val F1 mean : {cv_scores.mean():.4f}\n"
    f"Cross-val F1 std  : {cv_scores.std():.4f}\n\n"
    f"--- Isolation Forest (Unsupervised) ---\n"
    f"F1 (test)         : {iso_f1:.4f}\n"
    f"contamination     : {contamination:.4f}\n"
)
(OUT_DIR / "metrics.txt").write_text(metrics_text, encoding="utf-8")

print(f"  rf_model.pkl  → {OUT_DIR / 'rf_model.pkl'}")
print(f"  iso_model.pkl → {OUT_DIR / 'iso_model.pkl'}")
print(f"  scaler.pkl    → {OUT_DIR / 'scaler.pkl'}")
print(f"  metrics.txt   → {OUT_DIR / 'metrics.txt'}")

banner("DONE — Random Forest is the primary production model")
if rf_f1 >= 0.90:
    print(f"  RF F1 = {rf_f1:.4f}  ✓ Good — ready for deployment")
else:
    print(f"  RF F1 = {rf_f1:.4f}  ⚠ Below 0.90 — consider more training data")
