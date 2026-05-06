from pathlib import Path
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.preprocessing import StandardScaler

BASE_DIR = Path(__file__).resolve().parent
DATA_CSV = BASE_DIR / "training_data.csv"
PLOTS_DIR = BASE_DIR / "plots"
PLOTS_DIR.mkdir(exist_ok=True)

FEATURES = [
    "is_down",
    "memory_used_mb",
    "request_rate",
    "error_rate",
    "cpu_usage",
    "feign_failures_log",
]


def build_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    df = df.copy()

    for col in ["is_down", "memory_used_bytes", "request_rate", "error_rate", "cpu_usage", "feign_failures"]:
        df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0)

    df["memory_used_mb"] = df["memory_used_bytes"] / 1_048_576.0
    df["feign_failures_log"] = np.log1p(df["feign_failures"])

    x = df[FEATURES].to_numpy(dtype=float)
    y = (df["label"] != "normal").astype(int).to_numpy()
    return x, y


def preprocess(x_raw: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x_train_raw, x_test_raw, y_train, y_test = train_test_split(
        x_raw, y, test_size=0.2, random_state=42, stratify=y
    )

    # Keep the same clipping logic used by training script.
    clip_feature_names = ["memory_used_mb", "request_rate", "error_rate", "cpu_usage"]
    clip_feature_idx = [FEATURES.index(name) for name in clip_feature_names]
    for idx in clip_feature_idx:
        lo = float(np.percentile(x_train_raw[:, idx], 1))
        hi = float(np.percentile(x_train_raw[:, idx], 99))
        x_train_raw[:, idx] = np.clip(x_train_raw[:, idx], lo, hi)
        x_test_raw[:, idx] = np.clip(x_test_raw[:, idx], lo, hi)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train_raw)
    x_test = scaler.transform(x_test_raw)
    return x_train, x_test, y_train, y_test


def evaluate_model(name: str, model, x_train, y_train, x_test, y_test) -> dict:
    started = time.perf_counter()

    cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    scoring = {
        "f1": "f1",
        "roc_auc": "roc_auc",
        "pr_auc": "average_precision",
    }
    cv_scores = cross_validate(model, x_train, y_train, cv=cv, scoring=scoring, n_jobs=-1)

    model.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - started

    y_pred = model.predict(x_test)

    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(x_test)[:, 1]
    elif hasattr(model, "decision_function"):
        decision = model.decision_function(x_test)
        y_prob = 1.0 / (1.0 + np.exp(-decision))
    else:
        y_prob = y_pred.astype(float)

    return {
        "model": name,
        "cv_f1_mean": float(np.mean(cv_scores["test_f1"])),
        "cv_f1_std": float(np.std(cv_scores["test_f1"])),
        "cv_roc_auc_mean": float(np.mean(cv_scores["test_roc_auc"])),
        "cv_pr_auc_mean": float(np.mean(cv_scores["test_pr_auc"])),
        "test_f1": float(f1_score(y_test, y_pred)),
        "test_accuracy": float(accuracy_score(y_test, y_pred)),
        "test_precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "test_recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "test_roc_auc": float(roc_auc_score(y_test, y_prob)),
        "test_pr_auc": float(average_precision_score(y_test, y_prob)),
        "fit_seconds": float(fit_seconds),
    }


def main() -> None:
    if not DATA_CSV.exists():
        raise FileNotFoundError(f"Missing training data: {DATA_CSV}")

    df = pd.read_csv(DATA_CSV).drop_duplicates(subset=["timestamp", "job"])
    x_raw, y = build_features(df)
    x_train, x_test, y_train, y_test = preprocess(x_raw, y)

    models = [
        (
            "RandomForest",
            RandomForestClassifier(
                n_estimators=200,
                max_depth=None,
                min_samples_split=5,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        ),
        (
            "ExtraTrees",
            ExtraTreesClassifier(
                n_estimators=300,
                max_depth=None,
                min_samples_split=4,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        ),
        (
            "HistGradientBoosting",
            HistGradientBoostingClassifier(
                max_depth=8,
                learning_rate=0.08,
                max_iter=250,
                random_state=42,
            ),
        ),
        (
            "GradientBoosting",
            GradientBoostingClassifier(
                learning_rate=0.08,
                n_estimators=250,
                max_depth=3,
                random_state=42,
            ),
        ),
        (
            "LogisticRegression",
            LogisticRegression(
                max_iter=3000,
                class_weight="balanced",
                random_state=42,
            ),
        ),
        (
            "DummyBaseline",
            DummyClassifier(strategy="stratified", random_state=42),
        ),
    ]

    rows = []
    for name, model in models:
        try:
            print(f"[compare] Running {name} ...")
            rows.append(evaluate_model(name, model, x_train, y_train, x_test, y_test))
        except Exception as exc:
            print(f"[compare] {name} failed: {exc}")

    if not rows:
        raise RuntimeError("All model evaluations failed")

    result = pd.DataFrame(rows).sort_values("test_f1", ascending=False).reset_index(drop=True)

    csv_path = PLOTS_DIR / "model_comparison.csv"
    result.to_csv(csv_path, index=False)

    plt.figure(figsize=(10, 5), dpi=140)
    x_pos = np.arange(len(result))
    plt.bar(x_pos - 0.18, result["test_f1"], width=0.18, label="Test F1")
    plt.bar(x_pos, result["test_roc_auc"], width=0.18, label="Test ROC-AUC")
    plt.bar(x_pos + 0.18, result["test_pr_auc"], width=0.18, label="Test PR-AUC")
    plt.xticks(x_pos, result["model"], rotation=25, ha="right")
    plt.ylim(0, 1.02)
    plt.ylabel("Score")
    plt.title("Model Comparison on Holdout Set")
    plt.grid(axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()

    fig_path = PLOTS_DIR / "model_comparison.png"
    plt.savefig(fig_path)
    plt.close()

    top = result.iloc[0]
    summary = (
        "Model comparison summary\n"
        f"Rows: {len(df)}\n"
        f"Best model (by test_f1): {top['model']}\n"
        f"Best test_f1: {top['test_f1']:.4f}\n"
        f"Best test_roc_auc: {top['test_roc_auc']:.4f}\n"
        f"Best test_pr_auc: {top['test_pr_auc']:.4f}\n"
        "\nTop-6 results:\n"
        f"{result[['model','test_f1','test_roc_auc','test_pr_auc','cv_f1_mean','fit_seconds']].to_string(index=False)}\n"
    )
    summary_path = PLOTS_DIR / "model_comparison_summary.txt"
    summary_path.write_text(summary, encoding="utf-8")

    print(f"Saved: {csv_path}")
    print(f"Saved: {fig_path}")
    print(f"Saved: {summary_path}")


if __name__ == "__main__":
    main()
