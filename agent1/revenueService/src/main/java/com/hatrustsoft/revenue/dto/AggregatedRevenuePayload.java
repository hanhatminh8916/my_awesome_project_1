package com.hatrustsoft.revenue.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

// Matches AggregatedRevenuePayload record in manager/dataAggregationService
public record AggregatedRevenuePayload(
        @NotBlank String agentId,
        @NotBlank String sourceService,
        @NotBlank String reportId,
        @NotNull BigDecimal grossRevenue,
        @NotNull BigDecimal netRevenue,
        @NotBlank String currency,
        @NotNull OffsetDateTime reportedAt
) {}
