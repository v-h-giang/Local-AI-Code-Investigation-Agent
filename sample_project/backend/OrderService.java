package com.example;
public class OrderService {
    private OrderMapper orderMapper;
    public java.util.List<Order> getOrders() {
        return orderMapper.selectOrders();
    }
}
