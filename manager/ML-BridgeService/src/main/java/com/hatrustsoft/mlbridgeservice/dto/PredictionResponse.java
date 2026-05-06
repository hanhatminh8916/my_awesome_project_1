package com.hatrustsoft.mlbridgeservice.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Response from FastAPI /predict endpoint.
 * Field names must match PredictionOut in serve.py.
 */
public class PredictionResponse {

    private String job;

    @JsonProperty("service_name")
    private String serviceName;

    private String cluster;

    @JsonProperty("is_anomaly")
    private boolean anomaly;

    private String label;

    @JsonProperty("rf_confidence")
    private double rfConfidence;

    @JsonProperty("rf_anomaly_prob")
    private double rfAnomalyProb;

    @JsonProperty("recommended_threshold")
    private double recommendedThreshold;

    @JsonProperty("isolation_score")
    private double isolationScore;

    public PredictionResponse() {}

    public String getJob() { return job; }
    public void setJob(String job) { this.job = job; }

    public String getServiceName() { return serviceName; }
    public void setServiceName(String serviceName) { this.serviceName = serviceName; }

    public String getCluster() { return cluster; }
    public void setCluster(String cluster) { this.cluster = cluster; }

    public boolean isAnomaly() { return anomaly; }
    public void setAnomaly(boolean anomaly) { this.anomaly = anomaly; }

    public String getLabel() { return label; }
    public void setLabel(String label) { this.label = label; }

    public double getRfConfidence() { return rfConfidence; }
    public void setRfConfidence(double rfConfidence) { this.rfConfidence = rfConfidence; }

    public double getRfAnomalyProb() { return rfAnomalyProb; }
    public void setRfAnomalyProb(double rfAnomalyProb) { this.rfAnomalyProb = rfAnomalyProb; }

    public double getRecommendedThreshold() { return recommendedThreshold; }
    public void setRecommendedThreshold(double recommendedThreshold) { this.recommendedThreshold = recommendedThreshold; }

    public double getIsolationScore() { return isolationScore; }
    public void setIsolationScore(double isolationScore) { this.isolationScore = isolationScore; }
}
