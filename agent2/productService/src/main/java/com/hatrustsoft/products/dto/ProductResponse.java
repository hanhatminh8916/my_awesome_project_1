package com.hatrustsoft.products.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

public record ProductResponse(
        String id,
        String name,
        String sku,
        BigDecimal price,
        String category,
        String description,
        boolean active,
        OffsetDateTime createdAt
) {}
