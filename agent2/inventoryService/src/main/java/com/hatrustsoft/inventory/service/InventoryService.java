package com.hatrustsoft.inventory.service;

import com.hatrustsoft.inventory.dto.StockRequest;
import com.hatrustsoft.inventory.dto.StockResponse;
import com.hatrustsoft.inventory.model.InventoryItem;
import com.hatrustsoft.inventory.repository.InventoryRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.NoSuchElementException;

@Service
@RequiredArgsConstructor
@Slf4j
public class InventoryService {

    private final InventoryRepository inventoryRepository;

    public StockResponse getStock(String productId) {
        InventoryItem item = inventoryRepository.findFirstByProductId(productId)
                .orElseThrow(() -> new NoSuchElementException("No inventory found for product: " + productId));
        return toResponse(item);
    }

    public List<StockResponse> getAllStockForProduct(String productId) {
        return inventoryRepository.findByProductId(productId).stream()
                .map(this::toResponse)
                .toList();
    }

    @Transactional
    public StockResponse addStock(StockRequest request) {
        InventoryItem item = inventoryRepository
                .findByProductIdAndWarehouseId(request.productId(), request.warehouseId())
                .orElseGet(() -> InventoryItem.builder()
                        .productId(request.productId())
                        .warehouseId(request.warehouseId())
                        .build());
        item.setAvailableQuantity(item.getAvailableQuantity() + request.quantity());
        InventoryItem saved = inventoryRepository.save(item);
        log.info("Added {} units to product={} warehouse={}", request.quantity(), request.productId(), request.warehouseId());
        return toResponse(saved);
    }

    @Transactional
    public void reserve(String productId, int quantity) {
        InventoryItem item = inventoryRepository.findFirstByProductId(productId)
                .orElseThrow(() -> new NoSuchElementException("No inventory found for product: " + productId));
        if (item.getAvailableQuantity() < quantity) {
            throw new IllegalStateException("Insufficient stock for product: " + productId
                    + " (available=" + item.getAvailableQuantity() + ", requested=" + quantity + ")");
        }
        item.setAvailableQuantity(item.getAvailableQuantity() - quantity);
        item.setReservedQuantity(item.getReservedQuantity() + quantity);
        inventoryRepository.save(item);
        log.info("Reserved {} units of product={}", quantity, productId);
    }

    @Transactional
    public void release(String productId, int quantity) {
        InventoryItem item = inventoryRepository.findFirstByProductId(productId)
                .orElseThrow(() -> new NoSuchElementException("No inventory found for product: " + productId));
        int releasable = Math.min(quantity, item.getReservedQuantity());
        item.setReservedQuantity(item.getReservedQuantity() - releasable);
        item.setAvailableQuantity(item.getAvailableQuantity() + releasable);
        inventoryRepository.save(item);
        log.info("Released {} units of product={}", releasable, productId);
    }

    private StockResponse toResponse(InventoryItem item) {
        return new StockResponse(
                item.getProductId(),
                item.getWarehouseId(),
                item.getAvailableQuantity(),
                item.getReservedQuantity(),
                item.getUpdatedAt()
        );
    }
}
