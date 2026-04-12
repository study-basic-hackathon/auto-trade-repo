# Pythonの軽量な公式イメージを使用
FROM python:3.14.4-slim

# 作業ディレクトリを作成
WORKDIR /api

# 必要なパッケージをインストール
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

# コンテナ起動時にサーバーをポート8080で立ち上げる
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
