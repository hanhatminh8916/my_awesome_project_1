package com.hatrustsoft.mlbridgeservice.service;

import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import com.hatrustsoft.mlbridgeservice.dto.MetricsPayload;

/**
 * Queries Prometheus HTTP API to extract current metrics for all 16 services.
 *
 * KEY DESIGN: Prometheus job labels in this cluster are plain app names like
 * "inventory-service", "order-service", "central-api-gateway", etc.  Services
 * across clusters are differentiated by the "cluster" label (agent1/agent2/manager).
 *
 * Composite map key: cluster + "-" + jobName.replace("-service","")
 *   e.g.  cluster=agent1, job=inventory-service  →  "agent1-inventory"
 *         cluster=manager, job=alert-service      →  "manager-alert"
 *         cluster=manager, job=central-api-gateway →  "manager-central-api-gateway"
 *
 * Prometheus instant-query endpoint:
 *   GET {prometheusUrl}/api/v1/query?query={promQL}
 */
@Service
public class PrometheusQueryService {

    private static final Logger log = LoggerFactory.getLogger(PrometheusQueryService.class);

    /**
     * Composite key (cluster-service) → [serviceName, cluster]
     * Keys MUST match the transform: cluster + "-" + prometheusJob.replace("-service","")
     */
    private static final Map<String, String[]> JOB_META = new LinkedHashMap<>();

    static {
        // agent1 services  (Prometheus job labels: "inventory-service", "order-service", ...)
        JOB_META.put("agent1-inventory",            new String[]{"inventory",           "agent1"});
        JOB_META.put("agent1-order",                new String[]{"order",               "agent1"});
        JOB_META.put("agent1-revenue",              new String[]{"revenue",             "agent1"});
        JOB_META.put("agent1-product",              new String[]{"product",             "agent1"});
        // agent2 services
        JOB_META.put("agent2-inventory",            new String[]{"inventory",           "agent2"});
        JOB_META.put("agent2-order",                new String[]{"order",               "agent2"});
        JOB_META.put("agent2-revenue",              new String[]{"revenue",             "agent2"});
        JOB_META.put("agent2-product",              new String[]{"product",             "agent2"});
        // manager services  (Prometheus job labels: "central-api-gateway", "data-aggregation-service", ...)
        JOB_META.put("manager-central-api-gateway", new String[]{"central-api-gateway", "manager"});
        JOB_META.put("manager-data-aggregation",    new String[]{"data-aggregation",    "manager"});
        JOB_META.put("manager-central-analytics",   new String[]{"central-analytics",   "manager"});
        JOB_META.put("manager-alert",               new String[]{"alert",               "manager"});
        JOB_META.put("manager-automation-action",   new String[]{"automation-action",   "manager"});
        JOB_META.put("manager-report",              new String[]{"report",              "manager"});
        JOB_META.put("manager-master-data",         new String[]{"master-data",         "manager"});
        JOB_META.put("manager-ml-bridge",           new String[]{"ml-bridge",           "manager"});
    }

    /** Cluster names used to scope all Prometheus queries and avoid matching unrelated targets. */
    private static final String CLUSTERS = "agent1|agent2|manager";

    private final RestTemplate rest;
    private final String prometheusUrl;

    public PrometheusQueryService(RestTemplate rest,
                                  @Value("${ml.prometheus.url}") String prometheusUrl) {
        this.rest = rest;
        this.prometheusUrl = prometheusUrl;
    }

    /**
     * Returns one MetricsPayload per known service with current metrics from Prometheus.
     * Uses max() aggregation for up so that a service is considered up if ANY pod is up.
     * Missing metrics default to 0.0.
     */
    public List<MetricsPayload> fetchCurrentMetrics() {
        // Filter by cluster label — this matches the actual Prometheus labels in the cluster
        String clusterFilter = "cluster=~\"" + CLUSTERS + "\"";

        // max by (job,cluster): service is UP if any pod instance is up
        Map<String, Double> upMap    = instant(
                "max by (job,cluster)(up{" + clusterFilter + "})");
        Map<String, Double> memMap   = instant(
                "sum by (job,cluster)(jvm_memory_used_bytes{area=\"heap\"," + clusterFilter + "})");
        Map<String, Double> reqMap   = instant(
                "sum by (job,cluster)(rate(http_server_requests_seconds_count{" + clusterFilter + "}[1m]))");
        Map<String, Double> errMap   = instant(
                "sum by (job,cluster)(rate(http_server_requests_seconds_count{status=~\"5..\"," + clusterFilter + "}[1m]))");
        Map<String, Double> cpuMap   = instant(
                "avg by (job,cluster)(system_cpu_usage{" + clusterFilter + "})");
        Map<String, Double> feignMap = instant(
                "sum by (job,cluster)(increase(feign_call_failures_total{" + clusterFilter + "}[1m]))");

        log.debug("upMap keys: {}", upMap.keySet());

        List<MetricsPayload> results = new ArrayList<>();

        for (Map.Entry<String, String[]> entry : JOB_META.entrySet()) {
            String compositeKey = entry.getKey();   // e.g. "agent1-inventory"
            String serviceName  = entry.getValue()[0];
            String cluster      = entry.getValue()[1];

            double upVal = upMap.getOrDefault(compositeKey, 0.0);
            int isDown = upVal < 1.0 ? 1 : 0;

            MetricsPayload p = new MetricsPayload(
                    compositeKey,
                    serviceName,
                    cluster,
                    isDown,
                    isDown == 1 ? 0.0 : memMap.getOrDefault(compositeKey,   0.0),
                    isDown == 1 ? 0.0 : reqMap.getOrDefault(compositeKey,   0.0),
                    isDown == 1 ? 0.0 : errMap.getOrDefault(compositeKey,   0.0),
                    isDown == 1 ? 0.0 : cpuMap.getOrDefault(compositeKey,   0.0),
                    isDown == 1 ? 0.0 : feignMap.getOrDefault(compositeKey, 0.0)
            );
            results.add(p);
        }

        long downCount = results.stream().filter(p -> p.getIsDown() == 1).count();
        log.info("Fetched metrics for {} services ({} down) from Prometheus", results.size(), downCount);
        return results;
    }

    // ── Prometheus instant-query helper ──────────────────────────────────────

    /**
     * Executes a Prometheus instant query that MUST group by (job, cluster).
     * Returns a map keyed by composite "cluster-jobNormalized" where
     * jobNormalized = job.replace("-service", "").
     */
    @SuppressWarnings("unchecked")
    private Map<String, Double> instant(String promQL) {
        Map<String, Double> out = new HashMap<>();
        // Use URLEncoder + URI so Spring RestTemplate sends the query as-is
        // without template expansion or double-encoding.
        URI uri;
        try {
            uri = URI.create(prometheusUrl + "/api/v1/query?query="
                    + URLEncoder.encode(promQL, StandardCharsets.UTF_8));
        } catch (Exception e) {
            log.warn("Prometheus URI build failed for query [{}...]: {}",
                    promQL.substring(0, Math.min(60, promQL.length())), e.getMessage());
            return out;
        }
        try {
            Map<?, ?> body = rest.getForObject(uri, Map.class);
            if (body == null || !"success".equals(body.get("status"))) return out;

            Map<?, ?> data    = (Map<?, ?>) body.get("data");
            List<?>   results = (List<?>) data.get("result");
            if (results == null) return out;

            for (Object item : results) {
                Map<?, ?> row    = (Map<?, ?>) item;
                Map<?, ?> metric = (Map<?, ?>) row.get("metric");
                List<?>   value  = (List<?>) row.get("value");
                if (metric == null || value == null || value.size() < 2) continue;

                String job     = (String) metric.get("job");
                String cluster = (String) metric.get("cluster");
                if (job == null || cluster == null) continue;

                // Normalize: "inventory-service" → "inventory",
                //            "central-api-gateway" → "central-api-gateway" (no suffix)
                String jobNorm = job.endsWith("-service") ? job.substring(0, job.length() - 8) : job;
                String key = cluster + "-" + jobNorm;

                try {
                    double v = Double.parseDouble(value.get(1).toString());
                    // For metrics that can have multiple instances (e.g. up), keep the max
                    out.merge(key, v, Math::max);
                } catch (NumberFormatException e) {
                    out.putIfAbsent(key, 0.0);
                }
            }
        } catch (Exception e) {
            log.warn("Prometheus query failed [{}...]: {}",
                    promQL.substring(0, Math.min(60, promQL.length())), e.getMessage());
        }
        return out;
    }

}
