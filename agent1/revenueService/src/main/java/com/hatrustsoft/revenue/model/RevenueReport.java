package com.hatrustsoft.revenue.model;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Entity
@Table(name = "revenue_reports")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class RevenueReport {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private String id;

    @Column(nullable = false)
    private String agentId;

    @Column(unique = true, nullable = false)
    private String reportId;

    @Column(nullable = false, precision = 19, scale = 4)
    private BigDecimal grossRevenue;

    @Column(nullable = false, precision = 19, scale = 4)
    private BigDecimal netRevenue;

    @Column(nullable = false, length = 3)
    private String currency;

    @Column(nullable = false)
    private OffsetDateTime reportedAt;

    @CreationTimestamp
    @Column(updatable = false)
    private OffsetDateTime createdAt;
}
