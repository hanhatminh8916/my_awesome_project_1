package com.hatrustsoft.orders.feign;

import java.util.List;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

import com.hatrustsoft.orders.dto.ProductResponse;

@FeignClient(name = "product-service")
public interface ProductServiceClient {

    @GetMapping("/api/v1/products/{productId}")
    ProductResponse getProduct(@PathVariable("productId") String productId);

    @GetMapping("/api/v1/products")
    List<ProductResponse> getAllProducts();
}
