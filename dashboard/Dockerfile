# Dashboard-only image -- same deploy mechanism as mod2_dbt_project's
# Dockerfile (streamlit run on Cloud Run's $PORT), scoped down to just
# this service's own dependencies rather than mod2's shared dbt+jupyter+
# streamlit image, since this repo already separates concerns into their
# own top-level folders (cloud_functions/, dashboard/) instead of one
# multi-purpose container.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py common.py ./
COPY pages/ pages/
COPY .streamlit/ .streamlit/

# Cloud Run provides PORT, normally 8080.
CMD streamlit run app.py \
    --server.port=${PORT:-8080} \
    --server.address=0.0.0.0
