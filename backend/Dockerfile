FROM python:3.12-slim
WORKDIR /app
COPY server.py /app/server.py
RUN useradd --uid 10001 --create-home jy && mkdir /data && chown jy:jy /data
USER jy
ENV JY_DB_PATH=/data/reports.sqlite3
EXPOSE 8000
CMD ["python", "-u", "/app/server.py"]
