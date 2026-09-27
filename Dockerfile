FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home app \
    && mkdir -p /home/app/.cache/assistops && chown -R app:app /home/app/.cache
USER app
EXPOSE 8000
CMD ["uvicorn", "assistops.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
