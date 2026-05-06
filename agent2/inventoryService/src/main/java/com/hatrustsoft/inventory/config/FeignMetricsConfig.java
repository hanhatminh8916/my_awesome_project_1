package com.hatrustsoft.inventory.config;

import feign.codec.ErrorDecoder;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class FeignMetricsConfig {

    @Bean
    public ErrorDecoder feignErrorDecoder(MeterRegistry registry,
                                          @Value("${spring.application.name}") String appName) {
        Counter counter = Counter.builder("feign.call.failures")
                .description("Number of failed OpenFeign calls (non-2xx responses)")
                .tag("service", appName)
                .register(registry);
        ErrorDecoder defaultDecoder = new ErrorDecoder.Default();
        return (methodKey, response) -> {
            counter.increment();
            return defaultDecoder.decode(methodKey, response);
        };
    }
}
