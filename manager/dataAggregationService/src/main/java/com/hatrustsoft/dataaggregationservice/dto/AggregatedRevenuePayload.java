package com.hatrustsoft.dataaggregationservice.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record AggregatedRevenuePayload(
        @NotBlank String agentId,
        @NotBlank String sourceService,
        @NotBlank String reportId,
        @NotNull BigDecimal grossRevenue,
        @NotNull BigDecimal netRevenue,
        @NotBlank String currency,
        @NotNull OffsetDateTime reportedAt
) {
}
