FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY maria_prompt_web.txt ./maria_prompt_web.txt

EXPOSE 8080
CMD ["gunicorn", "backend.app:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120"]
