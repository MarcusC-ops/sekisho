FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY gate ./gate
COPY sdk ./sdk
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt
COPY agents ./agents
COPY scripts ./scripts
COPY deploy ./deploy
RUN useradd --create-home --uid 10001 sekisho && mkdir -p /data && chown sekisho:sekisho /data
USER sekisho
EXPOSE 8200
CMD ["python", "deploy/serve.py"]
