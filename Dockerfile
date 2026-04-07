FROM python:3.12-slim

WORKDIR /app

COPY setup.py pyproject.toml README.md ./
COPY trails/ ./trails/

RUN pip install --no-cache-dir .

EXPOSE 8765

CMD ["python", "-m", "trails.map_server", "--host", "0.0.0.0", "--port", "8765"]
