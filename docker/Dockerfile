FROM python:3.12-slim

WORKDIR /app

# ビルドコンテキストはプロジェクトルート (docker-compose.yml の context: .. を参照)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite / ログ等のローカル書き込み先（compose で ../data をマウントして永続化）
RUN mkdir -p /app/data

# API サーバのポート
EXPOSE 8000

# 既定は CLI 取得（API は compose の api サービスで起動）
CMD ["python", "-m", "app.fetch_gmail_imap"]
