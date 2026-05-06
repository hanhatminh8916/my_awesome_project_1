package com.hatrustsoft.orders.dto;

import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;

public record OrderRequest(
        @NotBlank String customerId,
        @NotBlank String currency,
        @NotEmpty List<@Valid OrderItemRequest> items
) {}
