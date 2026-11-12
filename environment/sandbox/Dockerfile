# Imagen del sandbox de QA de ADES-AI (regla 5: QA nunca ejecuta fuera de Docker).
# Se ejecuta con --network none, sin privilegios, con límites de CPU/RAM.
FROM python:3.11-slim
RUN pip install --no-cache-dir pytest==8.3.3 fastapi==0.115.0 httpx==0.27.2 \
        pydantic==2.9.2 uvicorn==0.30.6 requests==2.32.3 sqlalchemy==2.0.35 \
        bandit==1.7.10 \
    && useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /work
