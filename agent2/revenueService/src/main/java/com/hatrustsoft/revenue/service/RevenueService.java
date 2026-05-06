package com.hatrustsoft.revenue.service;

import com.hatrustsoft.revenue.dto.*;
import com.hatrustsoft.revenue.feign.DataAggregationServiceClient;
import com.hatrustsoft.revenue.feign.OrderServiceClient;
import com.hatrustsoft.revenue.model.RevenueReport;
import com.hatrustsoft.revenue.repository.RevenueReportRepository;
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
public class RevenueService {

    private final RevenueReportRepository revenueReportRepository;
    private final DataAggregationServiceClient dataAggregationClient;
    private final OrderServiceClient orderServiceClient;

    @Value("${app.agent-id:agent2}")
    private String agentId;

    @Transactional
    public RevenueReportResponse submitReport(RevenueReportRequest request) {
        revenueReportRepository.findByReportId(request.reportId()).ifPresent(existing -> {
            throw new IllegalStateException("Report already submitted: " + request.reportId());
        });

        RevenueReport report = RevenueReport.builder()
                .agentId(agentId)
                .reportId(request.reportId())
                .grossRevenue(request.grossRevenue())
                .netRevenue(request.netRevenue())
                .currency(request.currency())
                .reportedAt(request.reportedAt())
                .build();

        RevenueReport saved = revenueReportRepository.save(report);

        // Push to manager — non-fatal if manager is temporarily unavailable
        try {
            AggregatedRevenuePayload payload = new AggregatedRevenuePayload(
                    agentId, "revenue-service", saved.getReportId(),
                    saved.getGrossRevenue(), saved.getNetRevenue(),
                    saved.getCurrency(), saved.getReportedAt()
            );
            dataAggregationClient.sendAggregatedRevenue(payload);
            log.info("Pushed revenue report={} to manager for agentId={}", saved.getReportId(), agentId);
        } catch (Exception e) {
            log.warn("Failed to push revenue report={} to manager: {}", saved.getReportId(), e.getMessage());
        }

        return toResponse(saved);
    }

    public List<RevenueReportResponse> getReports() {
        return revenueReportRepository.findByAgentIdOrderByReportedAtDesc(agentId)
                .stream().map(this::toResponse).toList();
    }

    public RevenueReportResponse getById(String id) {
        return revenueReportRepository.findById(id)
                .map(this::toResponse)
                .orElseThrow(() -> new NoSuchElementException("Revenue report not found: " + id));
    }

    public RevenueSummaryResponse getSummary() {
        BigDecimal totalGross = revenueReportRepository.sumGrossRevenueByAgentId(agentId);
        BigDecimal totalNet = revenueReportRepository.sumNetRevenueByAgentId(agentId);
        long count = revenueReportRepository.countByAgentId(agentId);
        return new RevenueSummaryResponse(
                agentId,
                totalGross != null ? totalGross : BigDecimal.ZERO,
                totalNet != null ? totalNet : BigDecimal.ZERO,
                "USD",
                count
        );
    }

    private RevenueReportResponse toResponse(RevenueReport r) {
        return new RevenueReportResponse(
                r.getId(), r.getAgentId(), r.getReportId(),
                r.getGrossRevenue(), r.getNetRevenue(),
                r.getCurrency(), r.getReportedAt(), r.getCreatedAt()
        );
    }
}
