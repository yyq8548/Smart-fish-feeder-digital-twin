FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
CMD ["python", "mqtt_bridge.py"]
