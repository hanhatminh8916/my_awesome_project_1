package com.hatrustsoft.products.service;

import com.hatrustsoft.products.dto.ProductRequest;
import com.hatrustsoft.products.dto.ProductResponse;
import com.hatrustsoft.products.model.Product;
import com.hatrustsoft.products.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.NoSuchElementException;

@Service
@RequiredArgsConstructor
@Slf4j
public class ProductService {

    private final ProductRepository productRepository;

    public List<ProductResponse> getAllActive() {
        return productRepository.findByActiveTrue().stream()
                .map(this::toResponse)
                .toList();
    }

    public ProductResponse getById(String id) {
        return productRepository.findById(id)
                .map(this::toResponse)
                .orElseThrow(() -> new NoSuchElementException("Product not found: " + id));
    }

    public ProductResponse getBySku(String sku) {
        return productRepository.findBySku(sku)
                .map(this::toResponse)
                .orElseThrow(() -> new NoSuchElementException("Product not found by SKU: " + sku));
    }

    public List<ProductResponse> getByCategory(String category) {
        return productRepository.findByCategoryAndActiveTrue(category).stream()
                .map(this::toResponse)
                .toList();
    }

    @Transactional
    public ProductResponse create(ProductRequest request) {
        productRepository.findBySku(request.sku()).ifPresent(p -> {
            throw new IllegalStateException("SKU already exists: " + request.sku());
        });
        Product product = Product.builder()
                .name(request.name())
                .sku(request.sku())
                .price(request.price())
                .category(request.category())
                .description(request.description())
                .build();
        Product saved = productRepository.save(product);
        log.info("Created product id={} sku={}", saved.getId(), saved.getSku());
        return toResponse(saved);
    }

    @Transactional
    public ProductResponse update(String id, ProductRequest request) {
        Product product = productRepository.findById(id)
                .orElseThrow(() -> new NoSuchElementException("Product not found: " + id));
        product.setName(request.name());
        product.setSku(request.sku());
        product.setPrice(request.price());
        product.setCategory(request.category());
        product.setDescription(request.description());
        return toResponse(productRepository.save(product));
    }

    @Transactional
    public void deactivate(String id) {
        Product product = productRepository.findById(id)
                .orElseThrow(() -> new NoSuchElementException("Product not found: " + id));
        product.setActive(false);
        productRepository.save(product);
        log.info("Deactivated product id={}", id);
    }

    private ProductResponse toResponse(Product p) {
        return new ProductResponse(
                p.getId(), p.getName(), p.getSku(), p.getPrice(),
                p.getCategory(), p.getDescription(), p.isActive(), p.getCreatedAt()
        );
    }
}
