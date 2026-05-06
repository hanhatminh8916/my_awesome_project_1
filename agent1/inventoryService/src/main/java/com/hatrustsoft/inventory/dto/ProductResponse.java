package com.hatrustsoft.inventory.dto;

import java.math.BigDecimal;

public record ProductResponse(
        String id,
        String name,
        String sku,
        BigDecimal price,
        String category,
        boolean active
) {}
