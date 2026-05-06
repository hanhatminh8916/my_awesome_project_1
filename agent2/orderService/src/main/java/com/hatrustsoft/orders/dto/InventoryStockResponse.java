package com.hatrustsoft.orders.dto;

public record InventoryStockResponse(
        String productId,
        String warehouseId,
        int availableQuantity,
        int reservedQuantity
) {}
