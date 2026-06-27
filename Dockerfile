FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

CMD ["python", "main.py"]
