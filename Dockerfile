FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir aiogram==3.22.0
COPY bot.py /app/bot.py
RUN mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001:10001
CMD ["python", "bot.py"]
