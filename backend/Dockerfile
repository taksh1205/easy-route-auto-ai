FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.15.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Named volumes inherit ownership from the image path on first mount, so create the
# model cache here; otherwise Docker creates it root-owned and downloads fail.
RUN useradd -m app && mkdir -p /data/rag /home/app/.cache && chown -R app:app /app /data /home/app/.cache
USER app
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
