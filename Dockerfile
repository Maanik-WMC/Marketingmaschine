FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY deploy/n8n/workflows ./deploy/n8n/workflows

RUN pip install --no-cache-dir -e ".[prod]"

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "marketing_machine.api:app", "--host", "0.0.0.0", "--port", "8080"]
