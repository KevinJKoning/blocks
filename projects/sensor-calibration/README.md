# Polynomial ridge

Raw readings are cleaned (dropouts removed, connector spikes screened with a robust
residual cut), expanded into standardized polynomial features and fitted with ridge
regression. The exploration settled on a cubic (degree 3) with alpha 0.1: higher
degrees improved held-out RMSE by under 5 % and extrapolate badly past the calibrated
range (readings 0–10).
