FROM node:22-alpine AS frontend-build
WORKDIR /workspace
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY frontend ./frontend
ARG VITE_API_URL=/api
RUN cd frontend && VITE_API_URL=$VITE_API_URL npm run build

FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/bootstrap_owner.py ./bootstrap_owner.py
COPY --from=frontend-build /workspace/frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
