FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY benchmark ./benchmark

ENV GATEWAY_HOST=0.0.0.0
ENV GATEWAY_PORT=8801
ENV MOCK_LLM=true
ENV MOCK_JEV=true

EXPOSE 8801

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8801"]
