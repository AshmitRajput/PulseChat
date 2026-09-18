FROM python:3.14-slim
COPY . /app/
WORKDIR /app/backend
RUN apt update && apt install -y curl gcc libpq-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
