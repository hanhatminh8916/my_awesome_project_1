from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    PrecisionRecallDisplay,
    RocCurveDisplay,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, learning_curve, train_test_split, validation_curve
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


def main() -> None:
    if not DATA_CSV.exists():
        raise FileNotFoundError(f"Missing training data: {DATA_CSV}")

    df = pd.read_csv(DATA_CSV)
    df = df.drop_duplicates(subset=["timestamp", "job"])

    x_raw, y = build_features(df)

    x_train_raw, x_test_raw, y_train, y_test = train_test_split(
        x_raw, y, test_size=0.2, random_state=42, stratify=y
    )

    # Clip continuous features with train-derived bounds to match the training pipeline.
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

    base_model = RandomForestClassifier(
        n_estimators=200,
        min_samples_split=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    train_sizes = np.linspace(0.1, 1.0, 8)

    lsizes, ltrain_scores, lval_scores = learning_curve(
        base_model,
        x_train,
        y_train,
        cv=cv,
        train_sizes=train_sizes,
        scoring="f1",
        n_jobs=-1,
        shuffle=True,
        random_state=42,
    )

    depth_values = np.array([2, 4, 6, 8, 12, 16, 24, 32])
    vtrain_scores, vval_scores = validation_curve(
        RandomForestClassifier(
            n_estimators=200,
            min_samples_split=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ),
        x_train,
        y_train,
        param_name="max_depth",
        param_range=depth_values,
        cv=cv,
        scoring="f1",
        n_jobs=-1,
    )

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), dpi=140)

    axes[0].plot(lsizes, ltrain_scores.mean(axis=1), marker="o", label="Train F1")
    axes[0].plot(lsizes, lval_scores.mean(axis=1), marker="o", label="Validation F1")
    axes[0].fill_between(
        lsizes,
        ltrain_scores.mean(axis=1) - ltrain_scores.std(axis=1),
        ltrain_scores.mean(axis=1) + ltrain_scores.std(axis=1),
        alpha=0.15,
    )
    axes[0].fill_between(
        lsizes,
        lval_scores.mean(axis=1) - lval_scores.std(axis=1),
        lval_scores.mean(axis=1) + lval_scores.std(axis=1),
        alpha=0.15,
    )
    axes[0].set_title("Learning Curve (F1)")
    axes[0].set_xlabel("Training samples")
    axes[0].set_ylabel("F1 score")
    axes[0].grid(alpha=0.25)
    axes[0].legend()

    axes[1].plot(depth_values, vtrain_scores.mean(axis=1), marker="o", label="Train F1")
    axes[1].plot(depth_values, vval_scores.mean(axis=1), marker="o", label="Validation F1")
    axes[1].fill_between(
        depth_values,
        vtrain_scores.mean(axis=1) - vtrain_scores.std(axis=1),
        vtrain_scores.mean(axis=1) + vtrain_scores.std(axis=1),
        alpha=0.15,
    )
    axes[1].fill_between(
        depth_values,
        vval_scores.mean(axis=1) - vval_scores.std(axis=1),
        vval_scores.mean(axis=1) + vval_scores.std(axis=1),
        alpha=0.15,
    )
    axes[1].set_title("Validation Curve vs max_depth")
    axes[1].set_xlabel("max_depth")
    axes[1].set_ylabel("F1 score")
    axes[1].grid(alpha=0.25)
    axes[1].legend()

    fig.tight_layout()
    out_path = PLOTS_DIR / "overfit_underfit_diagnostics.png"
    fig.savefig(out_path)
    plt.close(fig)

    final_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        min_samples_split=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    final_model.fit(x_train, y_train)
    train_pred = final_model.predict(x_train)
    test_pred = final_model.predict(x_test)
    test_prob = final_model.predict_proba(x_test)[:, 1]

    train_f1 = f1_score(y_train, train_pred)
    test_f1 = f1_score(y_test, test_pred)
    test_roc_auc = roc_auc_score(y_test, test_prob)
    test_pr_auc = average_precision_score(y_test, test_prob)

    # Prediction diagnostics to inspect classification behavior on holdout set.
    fig2, axes2 = plt.subplots(2, 2, figsize=(13, 9), dpi=140)

    cm = confusion_matrix(y_test, test_pred)
    ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["normal", "anomaly"]).plot(
        ax=axes2[0, 0], colorbar=False
    )
    axes2[0, 0].set_title("Confusion Matrix (Test)")

    RocCurveDisplay.from_predictions(y_test, test_prob, ax=axes2[0, 1], name="RandomForest")
    axes2[0, 1].set_title(f"ROC Curve (AUC={test_roc_auc:.4f})")
    axes2[0, 1].grid(alpha=0.25)

    PrecisionRecallDisplay.from_predictions(
        y_test, test_prob, ax=axes2[1, 0], name="RandomForest"
    )
    axes2[1, 0].set_title(f"Precision-Recall Curve (AP={test_pr_auc:.4f})")
    axes2[1, 0].grid(alpha=0.25)

    axes2[1, 1].hist(test_prob[y_test == 0], bins=30, alpha=0.65, label="True normal")
    axes2[1, 1].hist(test_prob[y_test == 1], bins=30, alpha=0.65, label="True anomaly")
    axes2[1, 1].set_title("Predicted Anomaly Probability Distribution")
    axes2[1, 1].set_xlabel("P(anomaly)")
    axes2[1, 1].set_ylabel("Count")
    axes2[1, 1].grid(alpha=0.25)
    axes2[1, 1].legend()

    fig2.tight_layout()
    pred_out_path = PLOTS_DIR / "model_prediction_diagnostics.png"
    fig2.savefig(pred_out_path)
    plt.close(fig2)

    # Build epoch-like training curves using incremental tree growth.
    tree_steps = list(range(1, 101))
    train_losses: list[float] = []
    test_losses: list[float] = []
    train_accs: list[float] = []
    test_accs: list[float] = []

    progress_model = RandomForestClassifier(
        n_estimators=1,
        max_depth=None,
        min_samples_split=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
        warm_start=True,
    )

    for n_trees in tree_steps:
        progress_model.set_params(n_estimators=n_trees)
        progress_model.fit(x_train, y_train)

        train_prob_step = progress_model.predict_proba(x_train)
        test_prob_step = progress_model.predict_proba(x_test)
        train_pred_step = np.argmax(train_prob_step, axis=1)
        test_pred_step = np.argmax(test_prob_step, axis=1)

        train_losses.append(log_loss(y_train, train_prob_step, labels=[0, 1]))
        test_losses.append(log_loss(y_test, test_prob_step, labels=[0, 1]))
        train_accs.append(float((train_pred_step == y_train).mean()))
        test_accs.append(float((test_pred_step == y_test).mean()))

    fig3, axes3 = plt.subplots(2, 1, figsize=(9, 6), dpi=140, sharex=True)

    axes3[0].plot(tree_steps, train_losses, label="train")
    axes3[0].plot(tree_steps, test_losses, label="test")
    axes3[0].set_title("Loss")
    axes3[0].set_ylabel("log loss")
    axes3[0].grid(alpha=0.25)
    axes3[0].legend()

    axes3[1].plot(tree_steps, train_accs, label="train")
    axes3[1].plot(tree_steps, test_accs, label="test")
    axes3[1].set_title("Accuracy")
    axes3[1].set_xlabel("number of trees")
    axes3[1].set_ylabel("accuracy")
    axes3[1].grid(alpha=0.25)
    axes3[1].legend()

    fig3.tight_layout()
    progress_out_path = PLOTS_DIR / "model_training_progress_like_epochs.png"
    fig3.savefig(progress_out_path)
    plt.close(fig3)

    summary_path = PLOTS_DIR / "model_fit_summary.txt"
    report = classification_report(y_test, test_pred, target_names=["normal", "anomaly"])
    summary_text = (
        "Model fit diagnostics\n"
        f"Rows: {len(df)}\n"
        f"Train F1 (holdout split): {train_f1:.4f}\n"
        f"Test F1 (holdout split): {test_f1:.4f}\n"
        f"Test ROC AUC: {test_roc_auc:.4f}\n"
        f"Test PR AUC: {test_pr_auc:.4f}\n"
        "Interpretation hints:\n"
        "- Overfit: Train F1 high, Validation/Test F1 clearly lower.\n"
        "- Underfit: Both Train and Validation/Test F1 are low.\n"
        "- Good fit: Curves close and both high.\n"
        "\nClassification report (test):\n"
        f"{report}\n"
    )
    summary_path.write_text(summary_text, encoding="utf-8")

    print(f"Saved: {out_path}")
    print(f"Saved: {pred_out_path}")
    print(f"Saved: {progress_out_path}")
    print(f"Saved: {summary_path}")


if __name__ == "__main__":
    main()
