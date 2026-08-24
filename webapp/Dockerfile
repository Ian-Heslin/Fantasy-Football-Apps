# Packages the web app the same way whether it's run on a home Mac or a
# future cloud host -- see deploy/README.md. Expects app.db (and
# analytics.duckdb, for /teams and /coaches) to already exist; this image
# doesn't build them, it just serves what's already there.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
