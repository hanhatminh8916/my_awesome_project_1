package com.hatrustsoft.revenue;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.openfeign.EnableFeignClients;

@SpringBootApplication
@EnableFeignClients
public class RevenueApplication {

    public static void main(String[] args) {
        SpringApplication.run(RevenueApplication.class, args);
    }

}
