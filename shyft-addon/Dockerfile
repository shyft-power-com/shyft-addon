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
# Vom Workflow VOR dem Build geschrieben (siehe .github/workflows/builder.yaml, "Record build branch") -
# haelt fest, von welchem Git-Branch dieses Image stammt (Grundlage fuer den "TESTUMGEBUNG"-Hinweis, siehe
# load_build_branch in app.py). Wildcard statt fixem Dateinamen: ein lokaler "docker build" ohne diesen
# Schritt (z.B. Home-Assistant-Supervisor-Lokalbau) hat die Datei nicht, COPY darf dann nicht fehlschlagen.
COPY BUILD_BRANCH* .
COPY www /app/www
# Statische Demo-Dashboard-Daten (nur im Demo-Modus genutzt, siehe _load_demo_dashboard_data)
COPY demo_data /app/demo_data

# Startskript
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080

CMD ["/run.sh"]
