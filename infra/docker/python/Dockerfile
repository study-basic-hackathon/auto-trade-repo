# ============================================================
# builder stage: 依存パッケージを /app/.venv に解決するためだけのステージ
# ============================================================
FROM python:3.14.4-slim AS builder

# uvをインストール
COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /uvx /bin/

# 依存パッケージのインストール用ディレクトリ。
# venv（/app/.venv）とアプリコード（/api）を別ディレクトリに分けることで、
# ローカル開発時に compose.yaml の `./api:/api` でvolume mountしてもvenvが上書きされないようにしている
WORKDIR /app

# 依存定義ファイルをコピー
COPY api/pyproject.toml api/uv.lock ./

# uv syncでパッケージを /app/.venv にインストール。
# api パッケージ本体は /api 直下に配置して uvicorn から直接 import させるため、
# --no-install-project でプロジェクト自身のインストールはスキップする。
# --frozen で uv.lock から逸脱した解決を禁止し、ビルドの再現性を担保する
RUN uv sync --frozen --no-install-project

# ============================================================
# runtime stage: builder から /app/.venv だけ持ち込み、uv 本体は同梱しない
# ============================================================
FROM python:3.14.4-slim AS runtime

# Python の動作設定:
# - PYTHONDONTWRITEBYTECODE=1: .pyc を生成せず、volume mount 先に __pycache__ を作らない
# - PYTHONUNBUFFERED=1: 標準出力/標準エラーをバッファリングせず CloudWatch にすぐ流す
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# builderで構築した venv をそのままのパスでコピーする。
# venv 内のスクリプトは絶対パス（/app/.venv/bin/python）を参照するため、stage 間でパスを揃える必要がある
COPY --from=builder /app /app

# 仮想環境のパスを環境変数に追加
ENV PATH="/app/.venv/bin:$PATH"

# アプリケーションの作業ディレクトリ
WORKDIR /api

# アプリケーションコードをコピー。
# ローカルではこの内容が ./api:/api のvolume mountで上書きされ、
# 本番（ECS）ではvolume mountがないためここでCOPYした内容がそのまま使われる
COPY api/ /api/

# 非rootユーザーを作成し、/app と /api の所有権を付け替える
RUN useradd --create-home --uid 1000 app \
    && chown -R app:app /app /api

# 以降のプロセスは非rootユーザーで実行する
USER app

# コンテナ起動時にサーバーをポート8080で立ち上げる
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
