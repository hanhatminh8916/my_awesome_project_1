package com.hatrustsoft.mlbridgeservice.controller;

import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.hatrustsoft.mlbridgeservice.dto.MetricsPayload;
import com.hatrustsoft.mlbridgeservice.dto.PredictionResponse;
import com.hatrustsoft.mlbridgeservice.service.MlModelService;

import jakarta.validation.Valid;

/**
 * REST API — exposed for manual testing and integration.
 *
 * POST /api/ml/predict        — single service prediction
 * POST /api/ml/predict/batch  — multiple services at once
 */
@RestController
@RequestMapping("/api/ml")
public class MlBridgeController {

    private final MlModelService mlModelService;

    public MlBridgeController(MlModelService mlModelService) {
        this.mlModelService = mlModelService;
    }

    /**
     * Forward a single metrics snapshot to the ML model and return the prediction.
     */
    @PostMapping("/predict")
    public ResponseEntity<PredictionResponse> predict(@Valid @RequestBody MetricsPayload payload) {
        PredictionResponse result = mlModelService.predict(payload);
        if (result == null) {
            return ResponseEntity.status(503).build();
        }
        return ResponseEntity.ok(result);
    }

    /**
     * Batch prediction: forward multiple snapshots and return all predictions.
     * Useful for testing without waiting for the polling cycle.
     */
    @PostMapping("/predict/batch")
    public ResponseEntity<List<PredictionResponse>> predictBatch(
            @RequestBody List<MetricsPayload> payloads) {

        if (payloads == null || payloads.isEmpty()) {
            return ResponseEntity.badRequest().build();
        }

        List<PredictionResponse> responses = payloads.stream()
                .map(mlModelService::predict)
                .filter(r -> r != null)
                .toList();

        return ResponseEntity.ok(responses);
    }
}
