package com.hatrustsoft.revenue.controller;

import com.hatrustsoft.revenue.dto.RevenueReportRequest;
import com.hatrustsoft.revenue.dto.RevenueReportResponse;
import com.hatrustsoft.revenue.dto.RevenueSummaryResponse;
import com.hatrustsoft.revenue.service.RevenueService;
import io.micrometer.core.annotation.Timed;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/revenue")
@RequiredArgsConstructor
public class RevenueController {

    private final RevenueService revenueService;

    @Timed(value = "api.revenue.submit_report", description = "Submit a revenue report")
    @PostMapping("/reports")
    public ResponseEntity<RevenueReportResponse> submitReport(@Valid @RequestBody RevenueReportRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(revenueService.submitReport(request));
    }

    @GetMapping("/reports")
    public List<RevenueReportResponse> getReports() {
        return revenueService.getReports();
    }

    @GetMapping("/reports/{id}")
    public RevenueReportResponse getById(@PathVariable String id) {
        return revenueService.getById(id);
    }

    @Timed(value = "api.revenue.summary", description = "Get revenue summary")
    @GetMapping("/summary")
    public RevenueSummaryResponse getSummary() {
        return revenueService.getSummary();
    }
}
