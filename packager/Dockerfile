FROM python:3.7
LABEL APP_NAME="grafana-backup"
LABEL COMPONENT="dashboard_backup"
COPY ./src/ /src
WORKDIR /src
ENV APP_PATH "/src"
ENV PYTHONPATH "${PYTONPATH}:/src"
ENV PARAMS "PARAMS"
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD python grafana_backup.py ${PARAMS}
