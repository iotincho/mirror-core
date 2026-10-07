FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache

WORKDIR /app

#RUN groupadd --system el_espejo \
#    && useradd --system --gid el_espejo --create-home el_espejo

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --upgrade pip \
    && pip install . \
    && python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
#RUN mkdir -p /app/data/documents /app/data/extractions 

#RUN chown -R el_espejo:el_espejo /app
#USER el_espejo

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
