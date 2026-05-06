package com.hatrustsoft.revenue.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

public record RevenueReportRequest(
        @NotBlank String reportId,
        @NotNull @DecimalMin("0.00") BigDecimal grossRevenue,
        @NotNull @DecimalMin("0.00") BigDecimal netRevenue,
        @NotBlank String currency,
        @NotNull OffsetDateTime reportedAt
) {}
