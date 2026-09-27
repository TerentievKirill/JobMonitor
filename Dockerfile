FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY job_monitor ./job_monitor
COPY profile.yaml ./profile.yaml
COPY main.py collector.py filter_vacancies.py ./

CMD ["python", "main.py", "run"]
