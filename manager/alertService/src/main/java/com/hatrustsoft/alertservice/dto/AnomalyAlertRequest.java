package com.hatrustsoft.alertservice.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Anomaly alert request received from ML-BridgeService.
 */
public class AnomalyAlertRequest {

    private String job;

    @JsonProperty("service_name")
    private String serviceName;

    private String cluster;

    /** "anomaly" | "degraded" | "down" | "recovery" */
    private String severity;

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

    public AnomalyAlertRequest() {}

    public String getJob() { return job; }
    public void setJob(String job) { this.job = job; }

    public String getServiceName() { return serviceName; }
    public void setServiceName(String serviceName) { this.serviceName = serviceName; }

    public String getCluster() { return cluster; }
    public void setCluster(String cluster) { this.cluster = cluster; }

    public String getSeverity() { return severity; }
    public void setSeverity(String severity) { this.severity = severity; }

    public double getAnomalyProbability() { return anomalyProbability; }
    public void setAnomalyProbability(double anomalyProbability) { this.anomalyProbability = anomalyProbability; }

    public double getMemoryUsedBytes() { return memoryUsedBytes; }
    public void setMemoryUsedBytes(double memoryUsedBytes) { this.memoryUsedBytes = memoryUsedBytes; }

    public double getRequestRate() { return requestRate; }
    public void setRequestRate(double requestRate) { this.requestRate = requestRate; }

    public double getErrorRate() { return errorRate; }
    public void setErrorRate(double errorRate) { this.errorRate = errorRate; }

    public double getCpuUsage() { return cpuUsage; }
    public void setCpuUsage(double cpuUsage) { this.cpuUsage = cpuUsage; }

    public double getFeignFailures() { return feignFailures; }
    public void setFeignFailures(double feignFailures) { this.feignFailures = feignFailures; }

    public String getTimestamp() { return timestamp; }
    public void setTimestamp(String timestamp) { this.timestamp = timestamp; }
}
