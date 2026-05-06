package com.hatrustsoft.products.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import com.hatrustsoft.products.model.Product;

public interface ProductRepository extends JpaRepository<Product, String> {

    Optional<Product> findBySku(String sku);

    List<Product> findByActiveTrue();

    List<Product> findByCategoryAndActiveTrue(String category);
}
