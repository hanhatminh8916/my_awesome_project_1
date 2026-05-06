package com.hatrustsoft.revenue.feign;

import java.util.List;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.hatrustsoft.revenue.dto.OrderSummaryResponse;

@FeignClient(name = "order-service")
public interface OrderServiceClient {

    @GetMapping("/api/v1/orders")
    List<OrderSummaryResponse> getOrders(@RequestParam("status") String status);

    @GetMapping("/api/v1/orders/completed")
    List<OrderSummaryResponse> getCompletedOrders();
}
