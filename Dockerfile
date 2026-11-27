FROM node:22-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build


FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APOBANK_DB_PATH=/app/data/apobank.db \
    APOBANK_VAULT_PATH=/app/vault \
    APOBANK_UPLOAD_PATH=/app/data/uploads

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY --from=frontend-build /frontend/out ./frontend/out

# SQLite, Obsidian-Vault und Uploads muessen bei ECS ausserhalb des Containers
# persistent gemountet werden, etwa ueber EFS.
VOLUME ["/app/data", "/app/vault"]
EXPOSE 80

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "80"]
