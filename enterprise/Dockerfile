# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY enterprise/requirements.txt /app/enterprise/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r enterprise/requirements.txt; \
    else pip install --no-cache-dir -r enterprise/requirements.txt; fi
COPY *.js *.css *.html *.svg *.webmanifest /app/
COPY icons /app/icons
COPY enterprise /app/enterprise
RUN useradd --create-home --uid 10001 jiayang && install -d -m 0700 -o 10001 -g 10001 /home/jiayang/.local/share/jiayang && chmod -R a+rX /app
USER jiayang
EXPOSE 8765
CMD ["python", "-m", "enterprise", "serve"]
