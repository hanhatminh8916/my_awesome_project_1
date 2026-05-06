package com.hatrustsoft.orders.dto;

import java.math.BigDecimal;

public record OrderItemResponse(
        String id,
        String productId,
        int quantity,
        BigDecimal unitPrice
) {}
