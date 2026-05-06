package com.hatrustsoft.products.controller;

import com.hatrustsoft.products.dto.ProductRequest;
import com.hatrustsoft.products.dto.ProductResponse;
import com.hatrustsoft.products.service.ProductService;
import io.micrometer.core.annotation.Timed;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    @Timed(value = "api.products.list", description = "List active products")
    @GetMapping
    public List<ProductResponse> getAll(@RequestParam(required = false) String category) {
        if (category != null) return productService.getByCategory(category);
        return productService.getAllActive();
    }

    @GetMapping("/{id}")
    public ProductResponse getById(@PathVariable String id) {
        return productService.getById(id);
    }

    @GetMapping("/sku/{sku}")
    public ProductResponse getBySku(@PathVariable String sku) {
        return productService.getBySku(sku);
    }

    @Timed(value = "api.products.create", description = "Create a product")
    @PostMapping
    public ResponseEntity<ProductResponse> create(@Valid @RequestBody ProductRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(productService.create(request));
    }

    @Timed(value = "api.products.update", description = "Update a product")
    @PutMapping("/{id}")
    public ProductResponse update(@PathVariable String id, @Valid @RequestBody ProductRequest request) {
        return productService.update(id, request);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deactivate(@PathVariable String id) {
        productService.deactivate(id);
        return ResponseEntity.noContent().build();
    }
}
