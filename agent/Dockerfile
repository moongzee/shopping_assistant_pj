FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# 시스템 패키지(필요 시 확장)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python deps
COPY agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# App code
COPY agent /app/agent

EXPOSE 8000

# NOTE: .env 파일을 이미지에 포함하지 말고, EKS에서는 Secret/Env로 주입하세요.
CMD ["uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

