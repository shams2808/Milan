FROM python:3.11-slim

WORKDIR /app

# Milan operates on 100% Python standard library with zero external pip dependencies
COPY . /app

ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "milan.web"]
