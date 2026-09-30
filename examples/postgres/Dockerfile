FROM python:3.12-slim
ARG RELEASE=old
ENV RELEASE=${RELEASE} PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]==3.2.10"
COPY app.py .
USER 65534:65534
EXPOSE 8000
CMD ["python", "app.py"]
