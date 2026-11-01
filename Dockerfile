FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY cases ./cases
COPY deployment ./deployment
COPY tools/__init__.py tools/agent_result_bridge.py ./tools/
RUN mkdir -p outputs
EXPOSE 8080
CMD ["python", "-m", "app.chemcritic.cloud_server"]
