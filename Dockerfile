FROM python:3.12-slim
# Chromium renders the PDFs (Arabic shaping + RTL); Noto fonts give good Arabic glyphs
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-core fonts-noto-ui-core fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ENV QF_CHROME_BIN=chromium QF_INSTANCE_DIR=/data QF_DATABASE=/data/quoteflow.sqlite QF_SECURE_COOKIES=1
WORKDIR /app
COPY requirements.txt .
RUN mkdir -p /data
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
VOLUME /data
EXPOSE 8000
# SECRET_KEY must be provided at run time. One worker keeps SQLite simple; raise for Postgres later.
CMD ["sh", "-c", "gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:${PORT:-8000} run:app"]
