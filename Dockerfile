FROM python:3.12-slim
ARG GIT_REVISION=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/model-cache
ENV GIT_REVISION=${GIT_REVISION}
WORKDIR /workspace
COPY app/requirements.txt /workspace/app/requirements.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r app/requirements.txt
COPY app/ /workspace/app/
COPY tests/ /workspace/tests/
COPY QA.csv /workspace/QA.csv
COPY Dockerfile compose.yaml .dockerignore /workspace/
EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "app", "--host", "0.0.0.0", "--port", "8000"]
