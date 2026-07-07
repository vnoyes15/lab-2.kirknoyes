# Section 05: Docker — consistent local and production environments.
# Section 05 Hosting: Render or Railway — Docker-compatible, solo developer manageable.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY arx/ ./arx/
COPY scripts/ ./scripts/

EXPOSE 8000

CMD ["uvicorn", "arx.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
