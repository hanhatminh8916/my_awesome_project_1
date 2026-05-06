package com.hatrustsoft.mlbridgeservice.service;

import com.hatrustsoft.mlbridgeservice.dto.MetricsPayload;
import com.hatrustsoft.mlbridgeservice.dto.PredictionResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * Calls the Python FastAPI /predict endpoint to get ML predictions.
 */
@Service
public class MlModelService {

    private static final Logger log = LoggerFactory.getLogger(MlModelService.class);

    private final RestTemplate rest;
    private final String mlModelUrl;

    public MlModelService(RestTemplate rest,
                          @Value("${ml.model.url}") String mlModelUrl) {
        this.rest = rest;
        this.mlModelUrl = mlModelUrl;
    }

    /**
     * Calls FastAPI POST /predict for a single service metrics snapshot.
     *
     * @return PredictionResponse or null if the call fails
     */
    public PredictionResponse predict(MetricsPayload payload) {
        String url = mlModelUrl + "/predict";
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<MetricsPayload> entity = new HttpEntity<>(payload, headers);

            ResponseEntity<PredictionResponse> resp =
                    rest.exchange(url, HttpMethod.POST, entity, PredictionResponse.class);

            return resp.getBody();
        } catch (Exception e) {
            log.warn("ML model call failed for job={}: {}", payload.getJob(), e.getMessage());
            return null;
        }
    }
}
