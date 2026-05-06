package com.hatrustsoft.inventory.feign;

import com.hatrustsoft.inventory.dto.ProductResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

@FeignClient(name = "product-service")
public interface ProductServiceClient {

    @GetMapping("/api/v1/products/{productId}")
    ProductResponse getProduct(@PathVariable("productId") String productId);
}
