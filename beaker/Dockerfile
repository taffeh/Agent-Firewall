FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl git nano \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    google-adk \
    google-genai \
    fastapi \
    uvicorn \
    opentelemetry-sdk

WORKDIR /workspace

COPY beaker_agent.py .

EXPOSE 8080

CMD ["uvicorn", "beaker_agent:app", "--host", "0.0.0.0", "--port", "8080"]
