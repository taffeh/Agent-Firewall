FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl git nano apt-transport-https ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
    gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list

RUN apt-get update && apt-get install -y google-cloud-cli \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    google-adk \
    google-genai \
    fastapi \
    uvicorn \
    requests \
    google-auth \
    google-auth-httplib2 \
    opentelemetry-sdk

WORKDIR /workspace

COPY bunsen_agent.py .

EXPOSE 8081

CMD ["uvicorn", "bunsen_agent:app", "--host", "0.0.0.0", "--port", "8081"]
