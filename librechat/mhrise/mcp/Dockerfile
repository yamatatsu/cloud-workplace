FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastmcp==2.12.4 duckdb==1.4.1

COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]
