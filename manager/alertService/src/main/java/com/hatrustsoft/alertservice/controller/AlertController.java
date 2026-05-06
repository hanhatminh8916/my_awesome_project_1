package com.hatrustsoft.alertservice.controller;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.hatrustsoft.alertservice.dto.AnomalyAlertRequest;
import com.hatrustsoft.alertservice.dto.PrometheusWebhookRequest;
import com.hatrustsoft.alertservice.service.EmailAlertService;

/**
 * REST endpoint for receiving anomaly alerts from ML-BridgeService.
 *
 * POST /api/alerts/anomaly  — receive anomaly alert → send email
 */
@RestController
@RequestMapping("/api/alerts")
public class AlertController {

    private static final Logger log = LoggerFactory.getLogger(AlertController.class);

    private final EmailAlertService emailAlertService;

    public AlertController(EmailAlertService emailAlertService) {
        this.emailAlertService = emailAlertService;
    }

    @PostMapping("/anomaly")
    public ResponseEntity<Void> receiveAnomalyAlert(@RequestBody AnomalyAlertRequest req) {
        log.warn("Anomaly alert received: job={} cluster={} severity={} prob={}",
                req.getJob(), req.getCluster(), req.getSeverity(),
                String.format("%.3f", req.getAnomalyProbability()));

        emailAlertService.sendAnomalyAlert(req);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/recovery")
    public ResponseEntity<Void> receiveRecoveryAlert(@RequestBody AnomalyAlertRequest req) {
        log.info("Recovery alert received: job={} cluster={} severity={}",
                req.getJob(), req.getCluster(), req.getSeverity());

        emailAlertService.sendRecoveryAlert(req);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/prometheus")
    public ResponseEntity<Void> receivePrometheusAlert(@RequestBody PrometheusWebhookRequest req) {
        int count = req.getAlerts() == null ? 0 : req.getAlerts().size();
        log.warn("Prometheus webhook received: status={} alerts={}", req.getStatus(), count);

        emailAlertService.sendPrometheusAlerts(req);
        return ResponseEntity.accepted().build();
    }
}
