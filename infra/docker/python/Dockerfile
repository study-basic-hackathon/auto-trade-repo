# Pythonの軽量な公式イメージを使用
FROM python:3.14.4-slim

# uvをインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 依存パッケージのインストール用ディレクトリ
WORKDIR /app

# 依存定義ファイルをコピー
COPY api/pyproject.toml api/uv.lock ./

# uv syncでパッケージを /app/.venv にインストール
RUN uv sync --no-install-project

# 仮想環境のパスを環境変数に追加
ENV PATH="/app/.venv/bin:$PATH"

# アプリケーションの作業ディレクトリ
WORKDIR /api

# アプリケーションコードをコピー（ローカルはボリュームマウントで上書きされる）
COPY api/ /api/

# コンテナ起動時にサーバーをポート8080で立ち上げる
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
