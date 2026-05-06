package com.hatrustsoft.inventory.controller;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.hatrustsoft.inventory.dto.StockRequest;
import com.hatrustsoft.inventory.dto.StockResponse;
import com.hatrustsoft.inventory.service.InventoryService;

import io.micrometer.core.annotation.Timed;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;

@RestController
@RequestMapping("/api/v1/inventory")
@RequiredArgsConstructor
public class InventoryController {

    private final InventoryService inventoryService;

    @Timed(value = "api.inventory.get_stock", description = "Get stock for a product")
    @GetMapping("/{productId}/stock")
    public StockResponse getStock(@PathVariable String productId) {
        return inventoryService.getStock(productId);
    }

    @GetMapping("/{productId}/stock/all")
    public List<StockResponse> getAllStockForProduct(@PathVariable String productId) {
        return inventoryService.getAllStockForProduct(productId);
    }

    @Timed(value = "api.inventory.add_stock", description = "Add stock for a product")
    @PostMapping("/stock")
    public ResponseEntity<StockResponse> addStock(@Valid @RequestBody StockRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(inventoryService.addStock(request));
    }

    @Timed(value = "api.inventory.reserve", description = "Reserve stock for a product")
    @PutMapping("/{productId}/reserve")
    public ResponseEntity<Void> reserve(@PathVariable String productId,
                                        @RequestParam int quantity) {
        inventoryService.reserve(productId, quantity);
        return ResponseEntity.ok().build();
    }

    @PutMapping("/{productId}/release")
    public ResponseEntity<Void> release(@PathVariable String productId,
                                        @RequestParam int quantity) {
        inventoryService.release(productId, quantity);
        return ResponseEntity.ok().build();
    }
}
