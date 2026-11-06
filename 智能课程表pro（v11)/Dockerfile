ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

FROM ${NODE_IMAGE} AS frontend-build
ARG NPM_REGISTRY
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm config set registry "${NPM_REGISTRY}"
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime
ARG PIP_INDEX_URL
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/timetable.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt
COPY alembic.ini ./
COPY migrations ./migrations
COPY server ./server
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
