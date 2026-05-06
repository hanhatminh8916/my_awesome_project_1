package com.hatrustsoft.revenue.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

public record RevenueReportResponse(
        String id,
        String agentId,
        String reportId,
        BigDecimal grossRevenue,
        BigDecimal netRevenue,
        String currency,
        OffsetDateTime reportedAt,
        OffsetDateTime createdAt
) {}
