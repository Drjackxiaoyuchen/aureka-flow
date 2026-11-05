FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 PORT=8080 AUREKA_SERVER_MODE=1 AUREKA_ALLOWED_HOSTS=* \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY aureka_flow/ ./aureka_flow/
RUN python -m pip install . && useradd --uid 10001 --create-home appuser
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/api/health',timeout=4)"
CMD ["python", "-m", "aureka_flow", "--host", "0.0.0.0", "--no-browser"]
