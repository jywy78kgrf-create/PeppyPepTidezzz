# ATLAS backend — FastAPI quant/backtest/learn services
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPTDESK_DATA=/app/data \
    OPTDESK_STATE=/app/.state

WORKDIR /app

# deps first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# entrypoint: seed synthetic store if no chains present, then serve
RUN printf '#!/bin/sh\nset -e\nmkdir -p "$OPTDESK_DATA/chains" "$OPTDESK_STATE"\nif [ -z "$(ls -A "$OPTDESK_DATA/chains" 2>/dev/null)" ]; then\n  echo "[atlas] no chains found - generating synthetic sample store"\n  python -m optdesk.data.make_sample\nfi\nexec uvicorn optdesk.api.main:app --host 0.0.0.0 --port 8000\n' > /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)" || exit 1

CMD ["/usr/local/bin/entrypoint.sh"]
