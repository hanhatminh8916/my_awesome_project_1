package com.hatrustsoft.orders.dto;

import java.math.BigDecimal;

public record ProductResponse(
        String id,
        String name,
        String sku,
        BigDecimal price,
        String category,
        boolean active
) {}
