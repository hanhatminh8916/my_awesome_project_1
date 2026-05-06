package com.hatrustsoft.mlbridgeservice.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Payload sent to FastAPI /predict endpoint.
 * Field names must match the Pydantic MetricsInput model in serve.py.
 *
 * Preprocessing is done in serve.py (Python side):
 *   memory_used_bytes → memory_used_mb (÷ 1_048_576)
 *   feign_failures    → feign_failures_log (log1p)
 * Java side just sends raw values.
 */
public class MetricsPayload {

    private String job;

    @JsonProperty("service_name")
    private String serviceName;

    private String cluster;

    /** 1 if service is down (up==0), else 0 */
    @JsonProperty("is_down")
    private int isDown;

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

    public MetricsPayload() {}

    public MetricsPayload(String job, String serviceName, String cluster,
                          int isDown, double memoryUsedBytes, double requestRate,
                          double errorRate, double cpuUsage, double feignFailures) {
        this.job = job;
        this.serviceName = serviceName;
        this.cluster = cluster;
        this.isDown = isDown;
        this.memoryUsedBytes = memoryUsedBytes;
        this.requestRate = requestRate;
        this.errorRate = errorRate;
        this.cpuUsage = cpuUsage;
        this.feignFailures = feignFailures;
    }

    public String getJob() { return job; }
    public void setJob(String job) { this.job = job; }

    public String getServiceName() { return serviceName; }
    public void setServiceName(String serviceName) { this.serviceName = serviceName; }

    public String getCluster() { return cluster; }
    public void setCluster(String cluster) { this.cluster = cluster; }

    public int getIsDown() { return isDown; }
    public void setIsDown(int isDown) { this.isDown = isDown; }

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
}
