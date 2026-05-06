package com.hatrustsoft.inventory.repository;

import com.hatrustsoft.inventory.model.InventoryItem;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface InventoryRepository extends JpaRepository<InventoryItem, String> {

    Optional<InventoryItem> findByProductIdAndWarehouseId(String productId, String warehouseId);

    Optional<InventoryItem> findFirstByProductId(String productId);

    List<InventoryItem> findByProductId(String productId);
}
