package com.hatrustsoft.mlbridgeservice.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request sent to AlertService POST /api/alerts/anomaly
 * when ML model detects an anomaly.
 */
public class AlertTriggerRequest {

    private String job;

    @JsonProperty("service_name")
    private String serviceName;

    private String cluster;

    /** "degraded" | "down" | "anomaly" | "recovery" */
    private String severity;

    /** RF probability for anomaly class (0.0–1.0) */
    @JsonProperty("anomaly_probability")
    private double anomalyProbability;

    @JsonProperty("memory_used_bytes")
    private double memoryUsedBytes;

    @JsonProperty("request_rate")
    private double requestRate;

    @JsonProperty("error_rate")
    private double errorRate;

    @JsonProperty("cpu_usage")
    private double cpuUsage;

    @JsonProperty("feign_failures")
    private double feignFailures;

    private String timestamp;

    public AlertTriggerRequest() {}

    // Builder-style static factory
    public static AlertTriggerRequest from(MetricsPayload m, PredictionResponse p, String timestamp) {
        AlertTriggerRequest r = new AlertTriggerRequest();
        r.job               = m.getJob();
        r.serviceName       = m.getServiceName();
        r.cluster           = m.getCluster();
        r.anomalyProbability = p.getRfAnomalyProb();
        r.severity          = p.isAnomaly() ? "anomaly" : "normal";
        r.memoryUsedBytes   = m.getMemoryUsedBytes();
        r.requestRate       = m.getRequestRate();
        r.errorRate         = m.getErrorRate();
        r.cpuUsage          = m.getCpuUsage();
        r.feignFailures     = m.getFeignFailures();
        r.timestamp         = timestamp;
        return r;
    }

    public static AlertTriggerRequest fromRecovery(MetricsPayload m, String timestamp) {
        AlertTriggerRequest r = new AlertTriggerRequest();
        r.job                = m.getJob();
        r.serviceName        = m.getServiceName();
        r.cluster            = m.getCluster();
        r.anomalyProbability = 0.0;
        r.severity           = "recovery";
        r.memoryUsedBytes    = m.getMemoryUsedBytes();
        r.requestRate        = m.getRequestRate();
        r.errorRate          = m.getErrorRate();
        r.cpuUsage           = m.getCpuUsage();
        r.feignFailures      = m.getFeignFailures();
        r.timestamp          = timestamp;
        return r;
    }

    public String getJob() { return job; }
    public String getServiceName() { return serviceName; }
    public String getCluster() { return cluster; }
    public String getSeverity() { return severity; }
    public double getAnomalyProbability() { return anomalyProbability; }
    public double getMemoryUsedBytes() { return memoryUsedBytes; }
    public double getRequestRate() { return requestRate; }
    public double getErrorRate() { return errorRate; }
    public double getCpuUsage() { return cpuUsage; }
    public double getFeignFailures() { return feignFailures; }
    public String getTimestamp() { return timestamp; }
}
