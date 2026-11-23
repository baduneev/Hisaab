FROM node:22-alpine AS web
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY web ./web
COPY public ./public
COPY tokens.css base.css ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements.lock.txt ./
COPY api ./api
RUN pip install --no-cache-dir -r requirements.lock.txt && pip install --no-deps . && useradd --create-home hisaab
COPY migrations ./migrations
COPY alembic.ini ./
COPY --from=web /build/dist ./dist
USER hisaab
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8008 --workers 1"]
