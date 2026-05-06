package com.hatrustsoft.orders.controller;

import com.hatrustsoft.orders.dto.OrderRequest;
import com.hatrustsoft.orders.dto.OrderResponse;
import com.hatrustsoft.orders.service.OrderService;
import io.micrometer.core.annotation.Timed;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/orders")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;

    @Timed(value = "api.orders.create", description = "Create a new order")
    @PostMapping
    public ResponseEntity<OrderResponse> create(@Valid @RequestBody OrderRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(orderService.createOrder(request));
    }

    @Timed(value = "api.orders.list", description = "List orders")
    @GetMapping
    public List<OrderResponse> getOrders(@RequestParam(required = false) String status) {
        return orderService.getOrders(status);
    }

    @GetMapping("/completed")
    public List<OrderResponse> getCompleted() {
        return orderService.getCompletedOrders();
    }

    @GetMapping("/{id}")
    public OrderResponse getById(@PathVariable String id) {
        return orderService.getById(id);
    }

    @Timed(value = "api.orders.update_status", description = "Update order status")
    @PatchMapping("/{id}/status")
    public OrderResponse updateStatus(@PathVariable String id,
                                      @RequestParam String status) {
        return orderService.updateStatus(id, status);
    }
}
