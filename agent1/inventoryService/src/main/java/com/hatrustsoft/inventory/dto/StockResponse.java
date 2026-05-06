package com.hatrustsoft.inventory.dto;

import java.time.OffsetDateTime;

public record StockResponse(
        String productId,
        String warehouseId,
        int availableQuantity,
        int reservedQuantity,
        OffsetDateTime updatedAt
) {}
