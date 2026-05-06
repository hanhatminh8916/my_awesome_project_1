package com.hatrustsoft.alertservice.service;

import java.text.DecimalFormat;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.stereotype.Service;

import com.hatrustsoft.alertservice.dto.AnomalyAlertRequest;
import com.hatrustsoft.alertservice.dto.PrometheusWebhookRequest;
import com.hatrustsoft.alertservice.dto.PrometheusWebhookRequest.PrometheusAlert;

import jakarta.mail.internet.MimeMessage;

/**
 * Sends HTML email alerts via Gmail SMTP when ML model detects an anomaly.
 *
 * Required environment variables (or application.properties overrides):
 *   ALERT_EMAIL_FROM     — Gmail address (e.g. your-project@gmail.com)
 *   ALERT_EMAIL_TO       — recipient address
 *   ALERT_EMAIL_PASSWORD — Gmail App Password (NOT your Google account password)
 *
 * How to create a Gmail App Password:
 *   1. Enable 2-Step Verification on your Google account
 *   2. Go to https://myaccount.google.com/apppasswords
 *   3. Create a new App Password → copy the 16-char code
 *   4. Set ALERT_EMAIL_PASSWORD=<16-char code>
 */
@Service
public class EmailAlertService {

    private static final Logger log = LoggerFactory.getLogger(EmailAlertService.class);
    private static final DecimalFormat PCT = new DecimalFormat("0.0%");
    private static final DecimalFormat DEC = new DecimalFormat("0.000");
    private static final String GLOBAL_THROTTLE_KEY = "__global__";

    private final JavaMailSender mailSender;
    private final Mailbox defaultMailbox;
    private final Mailbox managerMailbox;
    private final Mailbox inventoryMailbox;
    private final Mailbox orderMailbox;
    private final Mailbox revenueMailbox;
    private final Mailbox productMailbox;
    private final String smtpHost;
    private final int smtpPort;
    private final boolean smtpAuth;
    private final boolean smtpStartTls;
    private final boolean smtpStartTlsRequired;
    private final int smtpConnectionTimeout;
    private final int smtpTimeout;
    private final int smtpWriteTimeout;
    private final long perJobCooldownSeconds;
    private final long globalCooldownSeconds;
    private final long correlationWindowSeconds;
    private final Map<String, JavaMailSender> smtpSenderCache = new ConcurrentHashMap<>();
    private final Map<String, Instant> lastEmailSentAt = new ConcurrentHashMap<>();
    private final Map<String, RecentAlert> recentAlertsByService = new ConcurrentHashMap<>();

    public EmailAlertService(JavaMailSender mailSender,
                             @Value("${alert.email.from}") String from,
                             @Value("${alert.email.password:${ALERT_EMAIL_PASSWORD:changeme}}") String password,
                             @Value("${alert.email.to}") String to,
                             @Value("${alert.email.manager.from}") String managerFrom,
                             @Value("${alert.email.manager.password}") String managerPassword,
                             @Value("${alert.email.manager.to}") String managerTo,
                             @Value("${alert.email.inventory.from}") String inventoryFrom,
                             @Value("${alert.email.inventory.password}") String inventoryPassword,
                             @Value("${alert.email.inventory.to}") String inventoryTo,
                             @Value("${alert.email.order.from}") String orderFrom,
                             @Value("${alert.email.order.password}") String orderPassword,
                             @Value("${alert.email.order.to}") String orderTo,
                             @Value("${alert.email.revenue.from}") String revenueFrom,
                             @Value("${alert.email.revenue.password}") String revenuePassword,
                             @Value("${alert.email.revenue.to}") String revenueTo,
                             @Value("${alert.email.product.from}") String productFrom,
                             @Value("${alert.email.product.password}") String productPassword,
                             @Value("${alert.email.product.to}") String productTo,
                             @Value("${spring.mail.host:smtp.gmail.com}") String smtpHost,
                             @Value("${spring.mail.port:587}") int smtpPort,
                             @Value("${spring.mail.properties.mail.smtp.auth:true}") boolean smtpAuth,
                             @Value("${spring.mail.properties.mail.smtp.starttls.enable:true}") boolean smtpStartTls,
                             @Value("${spring.mail.properties.mail.smtp.starttls.required:true}") boolean smtpStartTlsRequired,
                             @Value("${spring.mail.properties.mail.smtp.connectiontimeout:5000}") int smtpConnectionTimeout,
                             @Value("${spring.mail.properties.mail.smtp.timeout:5000}") int smtpTimeout,
                             @Value("${spring.mail.properties.mail.smtp.writetimeout:5000}") int smtpWriteTimeout,
                             @Value("${alert.email.cooldown-seconds:900}") long perJobCooldownSeconds,
                             @Value("${alert.email.global-cooldown-seconds:30}") long globalCooldownSeconds,
                             @Value("${alert.email.correlation-window-seconds:300}") long correlationWindowSeconds) {
        this.mailSender = mailSender;

        Mailbox fallbackDefaults = new Mailbox("alerts@example.com", "changeme", "ops@example.com");
        this.defaultMailbox = sanitizeMailbox(new Mailbox(from, password, to), fallbackDefaults);
        this.managerMailbox = sanitizeMailbox(new Mailbox(managerFrom, managerPassword, managerTo), this.defaultMailbox);
        this.inventoryMailbox = sanitizeMailbox(new Mailbox(inventoryFrom, inventoryPassword, inventoryTo), this.defaultMailbox);
        this.orderMailbox = sanitizeMailbox(new Mailbox(orderFrom, orderPassword, orderTo), this.defaultMailbox);
        this.revenueMailbox = sanitizeMailbox(new Mailbox(revenueFrom, revenuePassword, revenueTo), this.defaultMailbox);
        this.productMailbox = sanitizeMailbox(new Mailbox(productFrom, productPassword, productTo), this.defaultMailbox);

        this.smtpHost = smtpHost;
        this.smtpPort = smtpPort;
        this.smtpAuth = smtpAuth;
        this.smtpStartTls = smtpStartTls;
        this.smtpStartTlsRequired = smtpStartTlsRequired;
        this.smtpConnectionTimeout = smtpConnectionTimeout;
        this.smtpTimeout = smtpTimeout;
        this.smtpWriteTimeout = smtpWriteTimeout;

        this.perJobCooldownSeconds = perJobCooldownSeconds;
        this.globalCooldownSeconds = globalCooldownSeconds;
        this.correlationWindowSeconds = correlationWindowSeconds;
    }

    public void sendAnomalyAlert(AnomalyAlertRequest req) {
        dispatch(buildFromMlAlert(req, false));
    }

    public void sendRecoveryAlert(AnomalyAlertRequest req) {
        dispatch(buildFromMlAlert(req, true));
    }

    public void sendPrometheusAlerts(PrometheusWebhookRequest webhook) {
        List<PrometheusAlert> alerts = webhook == null ? null : webhook.getAlerts();
        if (alerts == null || alerts.isEmpty()) {
            log.debug("Prometheus webhook has no alerts to process");
            return;
        }

        for (PrometheusAlert alert : alerts) {
            AlertEmail event = buildFromPrometheusAlert(webhook, alert);
            dispatch(event);
        }
    }

    private void dispatch(AlertEmail alert) {
        CorrelationContext correlation = correlate(alert);
        String effectiveSeverity = resolveEffectiveSeverity(alert.severity(), correlation);
        boolean bypassPerJobCooldown = correlation.correlated() && !"recovery".equals(effectiveSeverity);
        AlertRoute route = resolveRoute(alert);
        Mailbox mailbox = resolveMailbox(route);

        if (shouldSuppress(alert, effectiveSeverity, bypassPerJobCooldown)) {
            log.info("Skipping alert email due to cooldown: source={} job={} cluster={} severity={} correlated={}",
                    alert.source(), alert.job(), alert.cluster(), effectiveSeverity, correlation.correlated());
            return;
        }

        String[] toRecipients = splitEmails(mailbox.to());
        if (toRecipients.length == 0) {
            log.warn("Skipping alert email because no recipients found for route={} job={} cluster={}",
                    route.name().toLowerCase(), alert.job(), alert.cluster());
            return;
        }

        String[] ccRecipients = resolveCcRecipients(route, toRecipients);

        try {
            JavaMailSender sender = resolveMailSender(mailbox);
            MimeMessage message = sender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, true, "UTF-8");

            helper.setFrom(mailbox.from());
            helper.setTo(toRecipients);
            if (ccRecipients.length > 0) {
                helper.setCc(ccRecipients);
            }
            helper.setSubject(buildSubject(alert, effectiveSeverity, correlation));
            helper.setText(buildHtmlBody(alert, effectiveSeverity, correlation), true);

            sender.send(message);
            log.info("Alert email sent for source={} job={} severity={} correlated={} route={} to={} cc={}",
                    alert.source(), alert.job(), effectiveSeverity, correlation.correlated(), route.name().toLowerCase(),
                    String.join(",", toRecipients),
                    ccRecipients.length > 0 ? String.join(",", ccRecipients) : "-");
        } catch (Exception e) {
            log.error("Failed to send alert email for source={} job={}: {}",
                    alert.source(), alert.job(), e.getMessage());
        }
    }

    private AlertEmail buildFromMlAlert(AnomalyAlertRequest req, boolean recovery) {
        String severity = recovery ? "recovery" : normalizeSeverity(req.getSeverity());
        return new AlertEmail(
                "ml-bridge",
                safe(req.getJob(), "unknown-job"),
                safe(req.getServiceName(), req.getJob()),
                safe(req.getCluster(), "unknown-cluster"),
                severity,
                req.getAnomalyProbability(),
                safe(req.getTimestamp(), Instant.now().toString()),
                req.getMemoryUsedBytes(),
                req.getRequestRate(),
                req.getErrorRate(),
                req.getCpuUsage(),
                req.getFeignFailures(),
                null,
                null,
                null
        );
    }

    private AlertEmail buildFromPrometheusAlert(PrometheusWebhookRequest webhook, PrometheusAlert alert) {
        Map<String, String> labels = alert.getLabels() == null ? Collections.emptyMap() : alert.getLabels();
        Map<String, String> annotations = alert.getAnnotations() == null ? Collections.emptyMap() : alert.getAnnotations();
        Map<String, String> commonLabels = webhook.getCommonLabels() == null ? Collections.emptyMap() : webhook.getCommonLabels();

        String status = safe(firstNonBlank(alert.getStatus(), webhook.getStatus()), "firing");
        boolean isResolved = "resolved".equalsIgnoreCase(status);

        String rawSeverity = firstNonBlank(labels.get("severity"), commonLabels.get("severity"), "warning");
        String mappedSeverity = isResolved ? "recovery" : mapPrometheusSeverity(rawSeverity);

        String job = firstNonBlank(labels.get("job"), labels.get("service"), labels.get("pod"), "unknown-job");
        String cluster = firstNonBlank(labels.get("cluster"), labels.get("namespace"), "unknown-cluster");
        String serviceName = firstNonBlank(labels.get("service"), labels.get("app"), job);

        return new AlertEmail(
                "prometheus",
                job,
                serviceName,
                cluster,
                mappedSeverity,
                0.0,
                safe(alert.getStartsAt(), Instant.now().toString()),
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                labels.get("alertname"),
                firstNonBlank(annotations.get("summary"), webhook.getCommonAnnotations() != null ? webhook.getCommonAnnotations().get("summary") : null),
                firstNonBlank(annotations.get("description"), webhook.getCommonAnnotations() != null ? webhook.getCommonAnnotations().get("description") : null)
        );
    }

    private boolean shouldSuppress(AlertEmail alert, String effectiveSeverity, boolean bypassPerJobCooldown) {
        if (!bypassPerJobCooldown) {
            String jobKey = buildPerJobKey(alert, effectiveSeverity);
            if (isThrottled(jobKey, perJobCooldownSeconds)) {
                return true;
            }
        }

        return isThrottled(GLOBAL_THROTTLE_KEY, globalCooldownSeconds);
    }

    private CorrelationContext correlate(AlertEmail alert) {
        String severity = normalizeSeverity(alert.severity());
        String serviceKey = buildServiceKey(alert.cluster(), alert.job());

        if ("recovery".equals(severity)) {
            recentAlertsByService.remove(serviceKey);
            return CorrelationContext.none();
        }

        Instant now = Instant.now();
        RecentAlert previous = recentAlertsByService.get(serviceKey);
        recentAlertsByService.put(serviceKey, new RecentAlert(alert.source(), severity, now, alert.alertName()));

        if (previous == null || correlationWindowSeconds <= 0) {
            return CorrelationContext.none();
        }

        boolean withinWindow = Duration.between(previous.observedAt(), now)
                .compareTo(Duration.ofSeconds(correlationWindowSeconds)) < 0;
        boolean differentSource = !previous.source().equalsIgnoreCase(alert.source());
        if (withinWindow && differentSource) {
            return new CorrelationContext(true, previous);
        }

        return CorrelationContext.none();
    }

    private String resolveEffectiveSeverity(String severity, CorrelationContext correlation) {
        String current = normalizeSeverity(severity);
        if (!correlation.correlated() || correlation.previous() == null) {
            return current;
        }

        String previous = normalizeSeverity(correlation.previous().severity());
        return severityRank(previous) > severityRank(current) ? previous : current;
    }

    private boolean isThrottled(String key, long cooldownSeconds) {
        if (cooldownSeconds <= 0) {
            return false;
        }

        Instant now = Instant.now();
        Duration cooldown = Duration.ofSeconds(cooldownSeconds);
        AtomicBoolean throttled = new AtomicBoolean(false);

        lastEmailSentAt.compute(key, (k, lastSentAt) -> {
            if (lastSentAt != null && Duration.between(lastSentAt, now).compareTo(cooldown) < 0) {
                throttled.set(true);
                return lastSentAt;
            }
            return now;
        });

        return throttled.get();
    }

    private String buildPerJobKey(AlertEmail alert, String effectiveSeverity) {
        return String.join("|",
                safe(alert.cluster(), "unknown-cluster"),
                safe(alert.job(), "unknown-job"),
                safe(effectiveSeverity, "unknown-severity"),
                safe(alert.source(), "unknown-source"));
    }

    private String buildServiceKey(String cluster, String job) {
        return String.join("|", safe(cluster, "unknown-cluster"), safe(job, "unknown-job"));
    }

    private AlertRoute resolveRoute(AlertEmail alert) {
        String fingerprint = String.join("|",
                safe(alert.job(), ""),
                safe(alert.serviceName(), ""),
                safe(alert.alertName(), ""))
                .toLowerCase();

        if (fingerprint.contains("inventory")) {
            return AlertRoute.INVENTORY;
        }
        if (fingerprint.contains("order")) {
            return AlertRoute.ORDER;
        }
        if (fingerprint.contains("revenue")) {
            return AlertRoute.REVENUE;
        }
        if (fingerprint.contains("product")) {
            return AlertRoute.PRODUCT;
        }
        return AlertRoute.MANAGER;
    }

    private Mailbox resolveMailbox(AlertRoute route) {
        return switch (route) {
            case INVENTORY -> inventoryMailbox;
            case ORDER -> orderMailbox;
            case REVENUE -> revenueMailbox;
            case PRODUCT -> productMailbox;
            case MANAGER -> managerMailbox;
        };
    }

    private String[] resolveCcRecipients(AlertRoute route, String[] toRecipients) {
        if (route == AlertRoute.MANAGER) {
            return new String[0];
        }

        Set<String> toSet = Arrays.stream(toRecipients)
                .map(String::toLowerCase)
                .collect(Collectors.toSet());

        return Arrays.stream(splitEmails(managerMailbox.to()))
                .filter(email -> !toSet.contains(email.toLowerCase()))
                .toArray(String[]::new);
    }

    private JavaMailSender resolveMailSender(Mailbox mailbox) {
        if (sameCredentials(mailbox, defaultMailbox)) {
            return mailSender;
        }

        String cacheKey = String.join("|", mailbox.from(), mailbox.password());
        return smtpSenderCache.computeIfAbsent(cacheKey, key -> createMailSender(mailbox));
    }

    private JavaMailSender createMailSender(Mailbox mailbox) {
        JavaMailSenderImpl sender = new JavaMailSenderImpl();
        sender.setHost(smtpHost);
        sender.setPort(smtpPort);
        sender.setUsername(mailbox.from());
        sender.setPassword(mailbox.password());

        Properties props = sender.getJavaMailProperties();
        props.put("mail.smtp.auth", String.valueOf(smtpAuth));
        props.put("mail.smtp.starttls.enable", String.valueOf(smtpStartTls));
        props.put("mail.smtp.starttls.required", String.valueOf(smtpStartTlsRequired));
        props.put("mail.smtp.connectiontimeout", String.valueOf(smtpConnectionTimeout));
        props.put("mail.smtp.timeout", String.valueOf(smtpTimeout));
        props.put("mail.smtp.writetimeout", String.valueOf(smtpWriteTimeout));
        return sender;
    }

    private boolean sameCredentials(Mailbox left, Mailbox right) {
        return safe(left.from(), "").equalsIgnoreCase(safe(right.from(), ""))
                && safe(left.password(), "").equals(safe(right.password(), ""));
    }

    private Mailbox sanitizeMailbox(Mailbox mailbox, Mailbox fallback) {
        return new Mailbox(
                firstNonBlank(trimToNull(mailbox.from()), fallback.from()),
                firstNonBlank(trimToNull(normalizePassword(mailbox.password())), normalizePassword(fallback.password())),
                firstNonBlank(trimToNull(mailbox.to()), fallback.to())
        );
    }

    private String[] splitEmails(String recipients) {
        if (recipients == null || recipients.isBlank()) {
            return new String[0];
        }

        return Arrays.stream(recipients.split("[,;]"))
                .map(String::trim)
                .filter(email -> !email.isBlank())
                .distinct()
                .toArray(String[]::new);
    }

    // ── Email content ──────────────────────────────────────────────────────────

    private String buildSubject(AlertEmail alert, String effectiveSeverity, CorrelationContext correlation) {
        if ("recovery".equals(effectiveSeverity)) {
            return String.format("✅ [RECOVERY] Service recovered — %s / %s",
                    alert.job(), alert.cluster());
        }

        String emoji = switch (effectiveSeverity) {
            case "down"     -> "🔴";
            case "degraded" -> "🟡";
            default         -> "⚠️";
        };

        String correlatedPrefix = correlation.correlated() ? "[CORRELATED] " : "";
        String sourceTag = correlation.correlated()
                ? "ML+PROM"
                : sourceTag(alert.source());

        return String.format("%s %s[%s][%s] Alert — %s / %s",
                emoji,
                correlatedPrefix,
                sourceTag,
                effectiveSeverity.toUpperCase(),
                alert.job(),
                alert.cluster());
    }

    private String buildHtmlBody(AlertEmail alert, String effectiveSeverity, CorrelationContext correlation) {
        String severityColor = switch (effectiveSeverity) {
            case "down"     -> "#e53e3e";
            case "degraded" -> "#dd6b20";
            case "recovery" -> "#2f855a";
            default         -> "#d69e2e";
        };

        boolean isDown = "down".equals(effectiveSeverity);
        boolean isRecovery = "recovery".equals(effectiveSeverity);
        boolean isPrometheus = "prometheus".equals(alert.source());

        double memMb = alert.memoryUsedBytes() / (1024.0 * 1024.0);

        String memVal = (isDown || isPrometheus) ? "N/A" : String.format("%.1f MB", memMb);
        String reqVal = (isDown || isPrometheus) ? "N/A" : DEC.format(alert.requestRate());
        String errVal = (isDown || isPrometheus) ? "N/A" : DEC.format(alert.errorRate());
        String cpuVal = (isDown || isPrometheus) ? "N/A" : String.format("%.1f%%", alert.cpuUsage() * 100);
        String feignVal = (isDown || isPrometheus) ? "N/A" : DEC.format(alert.feignFailures());
        String naStyle = (isDown || isPrometheus) ? "color:#a0aec0;font-style:italic;" : "font-family:monospace;";

        String anomalyProb = (isPrometheus || isRecovery)
                ? "N/A"
                : PCT.format(alert.anomalyProbability());

        String summary = safe(alert.summary(), "N/A");
        String description = safe(alert.description(), "N/A");
        String alertName = safe(alert.alertName(), "N/A");

        String sourceDisplay = correlation.correlated()
                ? "ML + Prometheus"
                : sourceDisplay(alert.source());

        String correlationNote = correlation.correlated() && correlation.previous() != null
                ? String.format("Correlated with previous %s alert (%s)",
                    sourceDisplay(correlation.previous().source()),
                    safe(correlation.previous().alertName(), correlation.previous().severity()))
                : "No cross-source correlation";

        String metricsNote = isRecovery
                ? "Recovery Snapshot"
                : isDown
                ? "Last Known State &mdash; <span style=\"color:#e53e3e;\">service is unreachable, no metrics available</span>"
                : "Current Metrics at Detection";

        return """
                <!DOCTYPE html>
                <html lang="en">
                <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"/></head>
                <body style="font-family:Arial,sans-serif;background:#f7fafc;padding:24px;margin:0;">
                  <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;
                              box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;">

                    <!-- Header -->
                    <div style="background:%(severityColor)s;padding:20px 24px;">
                      <h1 style="color:#fff;margin:0;font-size:20px;">
                        &#9888; Service Alert &mdash; %(severity)s
                      </h1>
                    </div>

                    <!-- Body -->
                    <div style="padding:24px;">
                      <table style="width:100%;border-collapse:collapse;font-size:14px;">
                        <tr style="background:#f0f4f8;">
                          <td style="padding:8px 12px;font-weight:bold;width:40%%;color:#4a5568;">Service Job</td>
                          <td style="padding:8px 12px;font-family:monospace;">%(job)s</td>
                        </tr>
                        <tr>
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Service Name</td>
                          <td style="padding:8px 12px;font-family:monospace;">%(serviceName)s</td>
                        </tr>
                        <tr style="background:#f0f4f8;">
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Cluster</td>
                          <td style="padding:8px 12px;font-family:monospace;">%(cluster)s</td>
                        </tr>
                        <tr>
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Severity</td>
                          <td style="padding:8px 12px;">
                            <span style="background:%(severityColor)s;color:#fff;padding:2px 10px;
                                         border-radius:12px;font-size:12px;font-weight:bold;">
                              %(severity)s
                            </span>
                          </td>
                        </tr>
                        <tr style="background:#f0f4f8;">
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Source</td>
                          <td style="padding:8px 12px;font-family:monospace;">%(source)s</td>
                        </tr>
                        <tr>
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Alert Name</td>
                          <td style="padding:8px 12px;font-family:monospace;">%(alertName)s</td>
                        </tr>
                        <tr style="background:#f0f4f8;">
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Correlation</td>
                          <td style="padding:8px 12px;">%(correlationNote)s</td>
                        </tr>
                        <tr>
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Summary</td>
                          <td style="padding:8px 12px;">%(summary)s</td>
                        </tr>
                        <tr style="background:#f0f4f8;">
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Description</td>
                          <td style="padding:8px 12px;">%(description)s</td>
                        </tr>
                        <tr>
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Anomaly Probability</td>
                          <td style="padding:8px 12px;font-weight:bold;color:%(severityColor)s;">%(anomalyProb)s</td>
                        </tr>
                        <tr style="background:#f0f4f8;">
                          <td style="padding:8px 12px;font-weight:bold;color:#4a5568;">Timestamp (UTC)</td>
                          <td style="padding:8px 12px;font-family:monospace;font-size:12px;">%(timestamp)s</td>
                        </tr>
                      </table>

                      <!-- Metrics section -->
                      <h3 style="margin:20px 0 10px;font-size:15px;color:#2d3748;border-bottom:1px solid #e2e8f0;padding-bottom:6px;">
                        %(metricsNote)s
                      </h3>
                      <table style="width:100%;border-collapse:collapse;font-size:14px;">
                        <thead>
                          <tr style="background:#edf2f7;">
                            <th style="text-align:left;padding:8px 12px;color:#4a5568;">Metric</th>
                            <th style="text-align:right;padding:8px 12px;color:#4a5568;">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td style="padding:7px 12px;">Memory Used (Heap)</td>
                            <td style="padding:7px 12px;text-align:right;%(naStyle)s">%(memVal)s</td>
                          </tr>
                          <tr style="background:#f0f4f8;">
                            <td style="padding:7px 12px;">Request Rate (req/s)</td>
                            <td style="padding:7px 12px;text-align:right;%(naStyle)s">%(reqVal)s</td>
                          </tr>
                          <tr>
                            <td style="padding:7px 12px;">Error Rate (5xx / s)</td>
                            <td style="padding:7px 12px;text-align:right;%(naStyle)s">%(errVal)s</td>
                          </tr>
                          <tr style="background:#f0f4f8;">
                            <td style="padding:7px 12px;">CPU Usage</td>
                            <td style="padding:7px 12px;text-align:right;%(naStyle)s">%(cpuVal)s</td>
                          </tr>
                          <tr>
                            <td style="padding:7px 12px;">Feign Failures (/ min)</td>
                            <td style="padding:7px 12px;text-align:right;%(naStyle)s">%(feignVal)s</td>
                          </tr>
                        </tbody>
                      </table>

                      <p style="margin-top:20px;font-size:12px;color:#718096;">
                        This alert was generated automatically by the unified notification pipeline
                        (Prometheus + ML-Bridge + AlertService).
                        Please investigate the service immediately.
                      </p>
                    </div>

                    <!-- Footer -->
                    <div style="background:#f7fafc;padding:12px 24px;font-size:11px;color:#a0aec0;text-align:center;">
                      Manager Microservices &bull; Unified Alerts
                    </div>
                  </div>
                </body>
                </html>
                """
                .replace("%(severityColor)s", severityColor)
                .replace("%(severity)s",      escapeHtml(effectiveSeverity))
                .replace("%(job)s",           escapeHtml(alert.job()))
                .replace("%(serviceName)s",   escapeHtml(alert.serviceName()))
                .replace("%(cluster)s",       escapeHtml(alert.cluster()))
                .replace("%(source)s",        escapeHtml(sourceDisplay))
                .replace("%(alertName)s",     escapeHtml(alertName))
                .replace("%(summary)s",       escapeHtml(summary))
                .replace("%(description)s",   escapeHtml(description))
                .replace("%(correlationNote)s", escapeHtml(correlationNote))
                .replace("%(anomalyProb)s",   escapeHtml(anomalyProb))
                .replace("%(timestamp)s",     escapeHtml(alert.timestamp()))
                .replace("%(metricsNote)s",   metricsNote)
                .replace("%(naStyle)s",       naStyle)
                .replace("%(memVal)s",        memVal)
                .replace("%(reqVal)s",        reqVal)
                .replace("%(errVal)s",        errVal)
                .replace("%(cpuVal)s",        cpuVal)
                .replace("%(feignVal)s",      feignVal);
    }

    private String sourceTag(String source) {
        return switch (safe(source, "unknown")) {
            case "ml-bridge" -> "ML";
            case "prometheus" -> "PROM";
            default -> "UNKNOWN";
        };
    }

    private String sourceDisplay(String source) {
        return switch (safe(source, "unknown")) {
            case "ml-bridge" -> "ML-Bridge";
            case "prometheus" -> "Prometheus";
            default -> "Unknown";
        };
    }

    private String mapPrometheusSeverity(String severity) {
        return switch (normalizeSeverity(severity)) {
            case "critical", "down" -> "down";
            case "warning", "degraded" -> "degraded";
            default -> "anomaly";
        };
    }

    private String normalizeSeverity(String severity) {
        if (severity == null || severity.isBlank()) {
            return "anomaly";
        }
        return severity.trim().toLowerCase();
    }

    private int severityRank(String severity) {
        return switch (normalizeSeverity(severity)) {
            case "down" -> 4;
            case "critical" -> 4;
            case "degraded" -> 3;
            case "warning" -> 3;
            case "anomaly" -> 2;
            case "recovery" -> 1;
            default -> 0;
        };
    }

    private String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }

        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return null;
    }

    private String safe(String value, String fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return value;
    }

    private String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private String normalizePassword(String password) {
        if (password == null) {
            return null;
        }
        return password.replaceAll("\\s+", "");
    }

    private String escapeHtml(String value) {
        if (value == null) {
            return "";
        }
        return value
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#39;");
    }

    private enum AlertRoute {
        INVENTORY,
        ORDER,
        REVENUE,
        PRODUCT,
        MANAGER
    }

    private record Mailbox(String from, String password, String to) {
    }

    private record AlertEmail(
            String source,
            String job,
            String serviceName,
            String cluster,
            String severity,
            double anomalyProbability,
            String timestamp,
            double memoryUsedBytes,
            double requestRate,
            double errorRate,
            double cpuUsage,
            double feignFailures,
            String alertName,
            String summary,
            String description
    ) {
    }

    private record RecentAlert(String source, String severity, Instant observedAt, String alertName) {
    }

    private record CorrelationContext(boolean correlated, RecentAlert previous) {
        private static CorrelationContext none() {
            return new CorrelationContext(false, null);
        }
    }
}
