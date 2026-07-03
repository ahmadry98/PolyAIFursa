FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY img_proc_app.py .

CMD ["python", "img_proc_app.py"]