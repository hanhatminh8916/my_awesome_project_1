package com.hatrustsoft.dataaggregationservice.controller;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.hatrustsoft.dataaggregationservice.dto.AggregatedRevenuePayload;

import jakarta.validation.Valid;

@RestController
@RequestMapping("/api/v1/aggregations")
public class AgentRevenueIngestionController {

    private static final Logger log = LoggerFactory.getLogger(AgentRevenueIngestionController.class);

    @PostMapping("/agent-revenue")
    public ResponseEntity<Void> ingest(@Valid @RequestBody AggregatedRevenuePayload payload) {
        log.info("Ingested revenue payload from agentId={}, reportId={}, netRevenue={} {}",
                payload.agentId(), payload.reportId(), payload.netRevenue(), payload.currency());
        return ResponseEntity.accepted().build();
    }
}
