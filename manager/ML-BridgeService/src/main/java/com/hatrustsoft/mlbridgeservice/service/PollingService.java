package com.hatrustsoft.mlbridgeservice.service;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import com.hatrustsoft.mlbridgeservice.dto.AlertTriggerRequest;
import com.hatrustsoft.mlbridgeservice.dto.MetricsPayload;
import com.hatrustsoft.mlbridgeservice.dto.PredictionResponse;

/**
 * Scheduled polling loop:
 *  Every 30 s → fetch Prometheus metrics → call ML model → alert if anomaly.
 */
@Service
public class PollingService {

    private static final Logger log = LoggerFactory.getLogger(PollingService.class);

    private final PrometheusQueryService prometheusQueryService;
    private final MlModelService mlModelService;
    private final RestTemplate rest;
    private final String alertServiceUrl;

    @Value("${ml.alert.dedup.cooldown-ms:900000}")
    private long alertDedupCooldownMs;

    @Value("${ml.anomaly.threshold.override:${ml.anomaly.threshold:-1}}")
    private double anomalyThresholdOverride;

    private final Map<String, AlertState> lastAlertByService = new ConcurrentHashMap<>();

    public PollingService(PrometheusQueryService prometheusQueryService,
                          MlModelService mlModelService,
                          RestTemplate rest,
                          @Value("${ml.alert-service.url}") String alertServiceUrl) {
        this.prometheusQueryService = prometheusQueryService;
        this.mlModelService         = mlModelService;
        this.rest                   = rest;
        this.alertServiceUrl        = alertServiceUrl;
    }

   
    @Scheduled(fixedDelayString = "${ml.polling.interval-ms:30000}",
               initialDelayString = "${ml.polling.initial-delay-ms:15000}")
    public void pollAndPredict() {
        log.info("[Polling] Starting metrics collection cycle");

        List<MetricsPayload> metrics;
        try {
            metrics = prometheusQueryService.fetchCurrentMetrics();
        } catch (Exception e) {
            log.error("[Polling] Failed to fetch metrics from Prometheus: {}", e.getMessage());
            return;
        }

        int anomalyCount = 0;
        String timestamp = Instant.now().toString();
        long now = System.currentTimeMillis();

        for (MetricsPayload m : metrics) {
            String serviceKey = m.getCluster() + "|" + m.getJob();

            PredictionResponse prediction = mlModelService.predict(m);

            if (prediction == null) {
                log.warn("[Polling] No prediction for job={} (ML service unavailable)", m.getJob());
                continue;
            }

                double anomalyProb = prediction.getRfAnomalyProb();
                double anomalyThreshold = resolveAnomalyThreshold(prediction);
                if (prediction.isAnomaly() && anomalyProb >= anomalyThreshold) {
                anomalyCount++;
                log.warn("[Polling] ANOMALY detected: job={} cluster={} prob={} threshold={}",
                        m.getJob(), m.getCluster(),
                    String.format("%.3f", anomalyProb),
                    String.format("%.3f", anomalyThreshold));
                triggerAlert(m, prediction, timestamp, now, serviceKey);
            } else {
                if (clearAlertState(serviceKey, m.getJob(), m.getCluster())) {
                    triggerRecoveryAlert(m, timestamp);
                }
                log.debug("[Polling] Normal/BelowThreshold: job={} prob={} threshold={}",
                    m.getJob(), String.format("%.3f", anomalyProb), String.format("%.3f", anomalyThreshold));
            }
        }

        log.info("[Polling] Cycle complete — {} / {} services anomalous",
                anomalyCount, metrics.size());
    }

    // ── Alert trigger ─────────────────────────────────────────────────────────

    private void triggerAlert(MetricsPayload m,
                              PredictionResponse p,
                              String timestamp,
                              long now,
                              String serviceKey) {
        String url = alertServiceUrl + "/api/alerts/anomaly";
        AlertTriggerRequest req = AlertTriggerRequest.from(m, p, timestamp);

        String signature = "ML|" + req.getSeverity();
        if (shouldSuppress(serviceKey, signature, req.getSeverity(), now, m.getJob(), m.getCluster())) {
            return;
        }

        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<AlertTriggerRequest> entity = new HttpEntity<>(req, headers);
            rest.exchange(url, HttpMethod.POST, entity, Void.class);
            log.info("[Polling] Alert triggered for job={} severity={}", m.getJob(), req.getSeverity());
        } catch (Exception e) {
            log.error("[Polling] Failed to trigger alert for job={}: {}", m.getJob(), e.getMessage());
        }
    }

    private void triggerRecoveryAlert(MetricsPayload m, String timestamp) {
        String url = alertServiceUrl + "/api/alerts/recovery";
        AlertTriggerRequest req = AlertTriggerRequest.fromRecovery(m, timestamp);
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<AlertTriggerRequest> entity = new HttpEntity<>(req, headers);
            rest.exchange(url, HttpMethod.POST, entity, Void.class);
            log.info("[Polling] Recovery alert triggered for job={} cluster={}", m.getJob(), m.getCluster());
        } catch (Exception e) {
            log.error("[Polling] Failed to trigger recovery alert for job={}: {}", m.getJob(), e.getMessage());
        }
    }

    private double resolveAnomalyThreshold(PredictionResponse prediction) {
        if (anomalyThresholdOverride > 0 && anomalyThresholdOverride <= 1) {
            return anomalyThresholdOverride;
        }

        double modelThreshold = prediction.getRecommendedThreshold();
        if (modelThreshold > 0 && modelThreshold <= 1) {
            return modelThreshold;
        }
        return 0.5;
    }

    private boolean shouldSuppress(String serviceKey,
                                   String signature,
                                   String severity,
                                   long now,
                                   String job,
                                   String cluster) {
        AlertState previous = lastAlertByService.get(serviceKey);
        if (previous == null) {
            lastAlertByService.put(serviceKey, new AlertState(signature, severity, now));
            return false;
        }

        long elapsed = now - previous.lastSentAtMillis();
        boolean escalation = severityRank(severity) > severityRank(previous.severity());

        if (elapsed >= alertDedupCooldownMs || escalation) {
            lastAlertByService.put(serviceKey, new AlertState(signature, severity, now));
            if (escalation && elapsed < alertDedupCooldownMs) {
                log.info("[Polling] Severity escalation, sending before cooldown: job={} cluster={} {} -> {} elapsedMs={} cooldownMs={}",
                        job, cluster, previous.severity(), severity, elapsed, alertDedupCooldownMs);
            }
            return false;
        }

        if (!previous.signature().equals(signature) || !previous.severity().equals(severity)) {
            // Keep the latest observed signature/severity but preserve original sent timestamp.
            lastAlertByService.put(serviceKey, new AlertState(signature, severity, previous.lastSentAtMillis()));
            log.info("[Polling] Suppressing signature change within cooldown: job={} cluster={} {} -> {} elapsedMs={} cooldownMs={}",
                    job, cluster, previous.signature(), signature, elapsed, alertDedupCooldownMs);
            return true;
        }

        log.info("[Polling] Suppressing duplicate alert: job={} cluster={} signature={} elapsedMs={} cooldownMs={}",
                job, cluster, signature, elapsed, alertDedupCooldownMs);
        return true;
    }

    private int severityRank(String severity) {
        if (severity == null) {
            return 0;
        }
        return switch (severity.toLowerCase()) {
            case "down" -> 3;
            case "degraded" -> 2;
            case "anomaly" -> 1;
            default -> 0;
        };
    }

    private boolean clearAlertState(String serviceKey, String job, String cluster) {
        AlertState removed = lastAlertByService.remove(serviceKey);
        if (removed != null) {
            log.info("[Polling] Alert state cleared after recovery: job={} cluster={} lastSignature={}",
                    job, cluster, removed.signature());
            return true;
        }
        return false;
    }

    private record AlertState(String signature, String severity, long lastSentAtMillis) {
    }
}
