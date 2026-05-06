package com.hatrustsoft.orders.feign;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.hatrustsoft.orders.dto.InventoryStockResponse;

@FeignClient(name = "inventory-service")
public interface InventoryServiceClient {

    @GetMapping("/api/v1/inventory/{productId}/stock")
    InventoryStockResponse getStock(@PathVariable("productId") String productId);

    @PutMapping("/api/v1/inventory/{productId}/reserve")
    void reserveStock(@PathVariable("productId") String productId,
                      @RequestParam("quantity") int quantity);
}
