package com.hatrustsoft.revenue.dto;

import java.math.BigDecimal;

public record RevenueSummaryResponse(
        String agentId,
        BigDecimal totalGrossRevenue,
        BigDecimal totalNetRevenue,
        String currency,
        long reportCount
) {}
