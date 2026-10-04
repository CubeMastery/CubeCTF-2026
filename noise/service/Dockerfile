FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --no-cache-dir -r requirements.txt

COPY schema.sql .
COPY noise ./noise
COPY noise_socket_server.py ./

ENV NOISE_DB=/data/noise.sqlite3
ENV NOISE_BIN_PORT=6426
VOLUME ["/data"]
EXPOSE 6426

CMD ["python", "noise_socket_server.py"]
