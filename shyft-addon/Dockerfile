# Basis-Image wird vom HA-Add-on-Builder je Architektur injiziert (siehe build.yaml).
# Lokaler Fallback-Build ohne Builder: python:3.13-alpine.
ARG BUILD_FROM=python:3.13-alpine
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# tzdata: tzlocal/APScheduler brauchen die Zeitzonendatenbank zur Laufzeit.
RUN apk add --no-cache tzdata

# Abhaengigkeiten zuerst (eigene Layer-Cache-Ebene)
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

# App-Code
COPY *.py .
COPY config.yaml .
COPY www /app/www
# Statische Demo-Dashboard-Daten (nur im Demo-Modus genutzt, siehe _load_demo_dashboard_data)
COPY demo_data /app/demo_data

# Startskript
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080

CMD ["/run.sh"]
