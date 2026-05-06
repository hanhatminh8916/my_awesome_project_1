package com.hatrustsoft.revenue.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

public record OrderSummaryResponse(
        String orderId,
        String agentId,
        String customerId,
        BigDecimal totalAmount,
        String currency,
        String status,
        OffsetDateTime createdAt
) {}
