package com.hatrustsoft.products.dto;

import java.math.BigDecimal;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record ProductRequest(
        @NotBlank String name,
        @NotBlank String sku,
        @NotNull @DecimalMin("0.01") BigDecimal price,
        String category,
        String description
) {}
