package com.hatrustsoft.revenue.feign;

import com.hatrustsoft.revenue.dto.AggregatedRevenuePayload;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

/**
 * FeignClient for cross-cluster call to manager/dataAggregationService.
 * URL resolved from property: manager.aggregation.base-url
 */
@FeignClient(name = "data-aggregation-service",
             url = "${manager.aggregation.base-url:http://manager-data-aggregation-service:8091}")
public interface DataAggregationServiceClient {

    @PostMapping("/api/v1/aggregations/agent-revenue")
    ResponseEntity<Void> sendAggregatedRevenue(@RequestBody AggregatedRevenuePayload payload);
}
