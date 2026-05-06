package com.hatrustsoft.products.repository;

import com.hatrustsoft.products.model.Product;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ProductRepository extends JpaRepository<Product, String> {

    Optional<Product> findBySku(String sku);

    List<Product> findByActiveTrue();

    List<Product> findByCategoryAndActiveTrue(String category);
}
