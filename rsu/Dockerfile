FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends mosquitto && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rsu/rsu.py rsu/mosquitto.conf ./
EXPOSE 1883 8080
CMD ["python", "-u", "rsu.py"]
