package com.hatrustsoft.inventory.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

public record StockRequest(
        @NotBlank String productId,
        @NotBlank String warehouseId,
        @Min(1) int quantity
) {}
