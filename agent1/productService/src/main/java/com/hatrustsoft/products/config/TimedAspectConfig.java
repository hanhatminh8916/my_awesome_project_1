package com.hatrustsoft.products.config;

import io.micrometer.core.aop.TimedAspect;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Enables processing of {@code @Timed} annotations on Spring-managed beans
 * via a Micrometer {@link TimedAspect}.
 */
@Configuration
public class TimedAspectConfig {

    @Bean
    public TimedAspect timedAspect(MeterRegistry registry) {
        return new TimedAspect(registry);
    }
}
