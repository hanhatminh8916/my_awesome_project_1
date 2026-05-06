package com.hatrustsoft.revenue.repository;

import com.hatrustsoft.revenue.model.RevenueReport;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

public interface RevenueReportRepository extends JpaRepository<RevenueReport, String> {

    List<RevenueReport> findByAgentIdOrderByReportedAtDesc(String agentId);

    Optional<RevenueReport> findByReportId(String reportId);

    @Query("SELECT SUM(r.grossRevenue) FROM RevenueReport r WHERE r.agentId = :agentId")
    BigDecimal sumGrossRevenueByAgentId(@Param("agentId") String agentId);

    @Query("SELECT SUM(r.netRevenue) FROM RevenueReport r WHERE r.agentId = :agentId")
    BigDecimal sumNetRevenueByAgentId(@Param("agentId") String agentId);

    long countByAgentId(String agentId);
}
