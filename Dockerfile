FROM python:3.10

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

RUN useradd -m -u 1000 user && \
    mkdir -p /app/output /app/tmp_brat && \
    chown -R user:user /app && \
    chmod -R 777 /app/output /app/tmp_brat

USER user

COPY --chown=user . .

EXPOSE 7860

CMD ["python", "run.py"]

