package com.hatrustsoft.orders.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.hatrustsoft.orders.model.Order;
import com.hatrustsoft.orders.model.OrderStatus;

public interface OrderRepository extends JpaRepository<Order, String> {

    List<Order> findByStatus(OrderStatus status);

    List<Order> findByAgentId(String agentId);

    List<Order> findByCustomerId(String customerId);

    List<Order> findByAgentIdAndStatus(String agentId, OrderStatus status);
}
