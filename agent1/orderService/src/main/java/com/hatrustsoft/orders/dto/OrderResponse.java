package com.hatrustsoft.orders.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

// Field name 'orderId' matches InventoryStockResponse used by revenueService FeignClient
public record OrderResponse(
        String orderId,
        String agentId,
        String customerId,
        BigDecimal totalAmount,
        String currency,
        String status,
        OffsetDateTime createdAt,
        List<OrderItemResponse> items
) {}
