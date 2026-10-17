FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home radar
COPY --chown=radar:radar app ./app
USER radar
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-access-log"]
