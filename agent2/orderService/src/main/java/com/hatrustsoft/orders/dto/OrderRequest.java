package com.hatrustsoft.orders.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;

import java.util.List;

public record OrderRequest(
        @NotBlank String customerId,
        @NotBlank String currency,
        @NotEmpty List<@Valid OrderItemRequest> items
) {}
