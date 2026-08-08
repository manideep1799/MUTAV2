#!/usr/bin/env python3
import os
from pathlib import Path

def generate_file(filepath: str, content: str):
    path = Path(filepath)
    if path.exists():
        print(f"Skipping {filepath} (already exists)")
        return
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"Created {filepath} successfully.")

def main():
    print("[SHIP] Mutagent Packaging Engine (Ship Stage)")
    print("------------------------------------------")
    
    backend_dockerfile = """
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
# Ensure local data directory exists for Chroma and SQLite
RUN mkdir -p data
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

    frontend_dockerfile = """
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
RUN npm install -g serve
EXPOSE 5173
CMD ["serve", "-s", "dist", "-l", "5173"]
"""

    docker_compose = """
version: '3.8'
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend/data:/app/data
      - ./backend/.env:/app/.env
    environment:
      - GROQ_API_KEY=${GROQ_API_KEY}

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "5173:5173"
    depends_on:
      - backend
"""

    generate_file("Dockerfile.backend", backend_dockerfile)
    generate_file("Dockerfile.frontend", frontend_dockerfile)
    generate_file("docker-compose.yml", docker_compose)
    
    print("\n[SUCCESS] Packaging complete! The agent is ready to be shipped.")
    print("Run `docker-compose up --build` to deploy to production.")

if __name__ == "__main__":
    main()
