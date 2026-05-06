#!/usr/bin/env python3
"""
Phase 6 — ML Inference Service (FastAPI)
=========================================
IMPORTANT: Preprocessing here MUST match train_model.py exactly:
  1. memory_used_bytes → memory_used_mb  (÷ 1_048_576)
  2. feign_failures    → feign_failures_log  (log1p)
  3. Feature order: is_down, memory_used_mb, request_rate,
                    error_rate, cpu_usage, feign_failures_log
  4. StandardScaler (loaded from scaler.pkl)

Run locally:
  uvicorn serve:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import pathlib
from contextlib import asynccontextmanager
from typing import List

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = pathlib.Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"

FEATURES = [
    "is_down",
    "memory_used_mb",        # = memory_used_bytes / 1_048_576
    "request_rate",
    "error_rate",
    "cpu_usage",
    "feign_failures_log",    # = log1p(feign_failures)
]

# ── Model cache ────────────────────────────────────────────────────────────────
_rf          = None
_iso         = None
_scaler      = None
_clip_bounds = {}     # {col_name: (p01, p99)} — loaded from clip_bounds.json
_rf_threshold = 0.5   # loaded from optimal_threshold.json when available

# Columns clipped during training (must match CLIP_FEAT_NAMES in train_model.py)
CLIP_FEAT_NAMES = ["memory_used_mb", "request_rate", "error_rate", "cpu_usage"]


def _load():
    """Load models and preprocessing artifacts once at startup."""
    global _rf, _iso, _scaler, _clip_bounds, _rf_threshold
    rf_path          = MODELS_DIR / "rf_model.pkl"
    iso_path         = MODELS_DIR / "iso_model.pkl"
    scaler_path      = MODELS_DIR / "scaler.pkl"
    clip_bounds_path = MODELS_DIR / "clip_bounds.json"
    threshold_path   = MODELS_DIR / "optimal_threshold.json"

    missing = [p for p in (rf_path, iso_path, scaler_path, clip_bounds_path) if not p.exists()]
    if missing:
        raise RuntimeError(
            f"Model files missing: {[str(p) for p in missing]}. "
            "Run train_model.py first."
        )

    _rf          = joblib.load(rf_path)
    _iso         = joblib.load(iso_path)
    _scaler      = joblib.load(scaler_path)
    raw_bounds   = json.loads(clip_bounds_path.read_text(encoding="utf-8"))
    _clip_bounds = {k: tuple(v) for k, v in raw_bounds.items()}

    if threshold_path.exists():
        raw_threshold = json.loads(threshold_path.read_text(encoding="utf-8"))
        _rf_threshold = float(raw_threshold.get("rf_anomaly_threshold", 0.5))
    else:
        _rf_threshold = 0.5

    print(f"[serve] Models loaded from {MODELS_DIR}")
    print(f"[serve] Clip bounds: {list(_clip_bounds.keys())}")
    print(f"[serve] RF anomaly threshold: {_rf_threshold:.3f}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load()
    yield


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ML Anomaly Detection Service",
    version="1.0.0",
    description="Predicts whether a microservice is in an anomalous state.",
    lifespan=lifespan,
)


# ── DTOs ───────────────────────────────────────────────────────────────────────
class MetricsInput(BaseModel):
    job: str            = Field(...,  example="agent1-inventory")
    service_name: str   = Field(...,  example="inventory")
    cluster: str        = Field(...,  example="agent1")
    is_down: int             = Field(0,   ge=0, le=1,  example=0)
    memory_used_bytes: float = Field(0.0, ge=0,        example=256_000_000.0)
    request_rate: float      = Field(0.0, ge=0,        example=8.5)
    error_rate: float        = Field(0.0, ge=0,        example=0.002)
    cpu_usage: float         = Field(0.0, ge=0, le=10, example=0.22)
    feign_failures: float    = Field(0.0, ge=0,        example=0.0)


class PredictionOut(BaseModel):
    job: str
    service_name: str
    cluster: str
    is_anomaly: bool
    label: str          # "normal" | "anomaly"
    rf_confidence: float    # RF probability for predicted class
    rf_anomaly_prob: float  # RF P(anomaly)
    recommended_threshold: float  # model-derived RF threshold (F1-max)
    isolation_score: float  # IsoForest score (lower = more anomalous)


class BatchPredictionRequest(BaseModel):
    services: List[MetricsInput]


class BatchPredictionResponse(BaseModel):
    predictions: List[PredictionOut]
    anomaly_count: int


# ── Helpers ────────────────────────────────────────────────────────────────────
def _preprocess(req: MetricsInput) -> np.ndarray:
    """
    Apply the SAME preprocessing as train_model.py (in order):
      1. memory_used_bytes → memory_used_mb      (÷ 1_048_576)
      2. feign_failures    → feign_failures_log  (log1p)
      3. Clip continuous features using train-derived p01/p99 bounds
      4. Feature array in FEATURES order (scaling done by caller via _scaler)
    """
    memory_used_mb     = req.memory_used_bytes / 1_048_576.0
    feign_failures_log = np.log1p(req.feign_failures)

    # Build mutable dict for easy clipping
    vals = {
        "memory_used_mb": memory_used_mb,
        "request_rate":   req.request_rate,
        "error_rate":     req.error_rate,
        "cpu_usage":      req.cpu_usage,
    }

    # Apply clip bounds (from training) to continuous features
    for col in CLIP_FEAT_NAMES:
        if col in _clip_bounds:
            p01, p99 = _clip_bounds[col]
            vals[col] = float(np.clip(vals[col], p01, p99))

    return np.array([[
        float(req.is_down),
        vals["memory_used_mb"],
        vals["request_rate"],
        vals["error_rate"],
        vals["cpu_usage"],
        feign_failures_log,
    ]])


def _predict_one(req: MetricsInput) -> PredictionOut:
    X_raw    = _preprocess(req)
    X_scaled = _scaler.transform(X_raw)

    rf_pred  = int(_rf.predict(X_scaled)[0])
    rf_proba = _rf.predict_proba(X_scaled)[0]     # [p_normal, p_anomaly]
    rf_anomaly_prob = float(rf_proba[1])
    rf_confidence   = float(rf_proba[rf_pred])

    # IsolationForest predicts -1 for outlier, 1 for inlier.
    iso_pred  = int(_iso.predict(X_scaled)[0])
    iso_raw   = float(_iso.score_samples(X_scaled)[0])  # negative = more anomalous

    # Model-driven ensemble: anomaly if RF flags anomaly OR IsoForest flags outlier.
    # This improves sensitivity for unusual high-CPU shapes that RF may classify as normal.
    is_anomaly = bool((rf_pred == 1) or (iso_pred == -1))
    label      = "anomaly" if is_anomaly else "normal"

    return PredictionOut(
        job=req.job,
        service_name=req.service_name,
        cluster=req.cluster,
        is_anomaly=is_anomaly,
        label=label,
        rf_confidence=rf_confidence,
        rf_anomaly_prob=rf_anomaly_prob,
        recommended_threshold=float(_rf_threshold),
        isolation_score=iso_raw,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "models_loaded": _rf is not None}


@app.post("/predict", response_model=PredictionOut, tags=["prediction"])
def predict(req: MetricsInput):
    """Predict anomaly status for a single service snapshot."""
    if _rf is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")
    return _predict_one(req)


@app.post("/predict/batch", response_model=BatchPredictionResponse, tags=["prediction"])
def predict_batch(req: BatchPredictionRequest):
    """Predict anomaly status for multiple services in one call."""
    if _rf is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")
    if not req.services:
        raise HTTPException(status_code=400, detail="services list is empty")

    preds = [_predict_one(s) for s in req.services]
    anomaly_count = sum(1 for p in preds if p.is_anomaly)

    return BatchPredictionResponse(predictions=preds, anomaly_count=anomaly_count)
