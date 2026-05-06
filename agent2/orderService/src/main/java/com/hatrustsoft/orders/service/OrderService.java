package com.hatrustsoft.orders.service;

import com.hatrustsoft.orders.dto.*;
import com.hatrustsoft.orders.feign.InventoryServiceClient;
import com.hatrustsoft.orders.feign.ProductServiceClient;
import com.hatrustsoft.orders.model.Order;
import com.hatrustsoft.orders.model.OrderItem;
import com.hatrustsoft.orders.model.OrderStatus;
import com.hatrustsoft.orders.repository.OrderRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;
import java.util.NoSuchElementException;

@Service
@RequiredArgsConstructor
@Slf4j
public class OrderService {

    private final OrderRepository orderRepository;
    private final InventoryServiceClient inventoryClient;
    private final ProductServiceClient productClient;

    @Value("${app.agent-id:agent2}")
    private String agentId;

    @Transactional
    public OrderResponse createOrder(OrderRequest request) {
        // Validate stock availability and compute total
        BigDecimal total = BigDecimal.ZERO;
        for (OrderItemRequest item : request.items()) {
            var stock = inventoryClient.getStock(item.productId());
            if (stock.availableQuantity() < item.quantity()) {
                throw new IllegalStateException(
                        "Insufficient stock for product: " + item.productId()
                        + " (available=" + stock.availableQuantity() + ", requested=" + item.quantity() + ")");
            }
            total = total.add(item.unitPrice().multiply(BigDecimal.valueOf(item.quantity())));
        }

        Order order = Order.builder()
                .agentId(agentId)
                .customerId(request.customerId())
                .totalAmount(total)
                .currency(request.currency())
                .status(OrderStatus.PENDING)
                .build();

        List<OrderItem> orderItems = request.items().stream()
                .map(req -> OrderItem.builder()
                        .order(order)
                        .productId(req.productId())
                        .quantity(req.quantity())
                        .unitPrice(req.unitPrice())
                        .build())
                .toList();
        order.getItems().addAll(orderItems);

        Order saved = orderRepository.save(order);

        // Reserve inventory after persisting the order
        request.items().forEach(item ->
                inventoryClient.reserveStock(item.productId(), item.quantity()));

        log.info("Created order id={} agentId={} customerId={} total={} {}",
                saved.getId(), agentId, request.customerId(), total, request.currency());
        return toResponse(saved);
    }

    public List<OrderResponse> getOrders(String status) {
        if (status != null) {
            return orderRepository.findByStatus(OrderStatus.valueOf(status.toUpperCase()))
                    .stream().map(this::toResponse).toList();
        }
        return orderRepository.findAll().stream().map(this::toResponse).toList();
    }

    public List<OrderResponse> getCompletedOrders() {
        return orderRepository.findByStatus(OrderStatus.DELIVERED)
                .stream().map(this::toResponse).toList();
    }

    public OrderResponse getById(String id) {
        return orderRepository.findById(id)
                .map(this::toResponse)
                .orElseThrow(() -> new NoSuchElementException("Order not found: " + id));
    }

    @Transactional
    public OrderResponse updateStatus(String id, String status) {
        Order order = orderRepository.findById(id)
                .orElseThrow(() -> new NoSuchElementException("Order not found: " + id));
        order.setStatus(OrderStatus.valueOf(status.toUpperCase()));
        log.info("Updated order id={} status={}", id, status);
        return toResponse(orderRepository.save(order));
    }

    private OrderResponse toResponse(Order o) {
        List<OrderItemResponse> itemResponses = o.getItems().stream()
                .map(i -> new OrderItemResponse(i.getId(), i.getProductId(), i.getQuantity(), i.getUnitPrice()))
                .toList();
        return new OrderResponse(
                o.getId(), o.getAgentId(), o.getCustomerId(),
                o.getTotalAmount(), o.getCurrency(),
                o.getStatus().name(), o.getCreatedAt(), itemResponses
        );
    }
}
