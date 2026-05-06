# ============================================================
# builder stage: 依存パッケージを /app/.venv に解決するためだけのステージ
# ============================================================
FROM python:3.14.4-slim AS builder

# uvをインストール
COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /uvx /bin/

# 依存パッケージのインストール用ディレクトリ
WORKDIR /app

# 依存定義ファイルをコピー
COPY inference/pyproject.toml inference/uv.lock ./

# uv syncでパッケージを /app/.venv にインストール。
# inference は entry.py を python から直接実行する単発スクリプトのため、
# --no-install-project でプロジェクト自身のインストールはスキップする。
# --frozen で uv.lock から逸脱した解決を禁止し、ビルドの再現性を担保する
RUN uv sync --frozen --no-install-project

# ============================================================
# runtime stage: builder から /app/.venv だけ持ち込み、uv 本体は同梱しない
# ============================================================
FROM python:3.14.4-slim AS runtime

# Python の動作設定:
# - PYTHONDONTWRITEBYTECODE=1: .pyc を生成しない
# - PYTHONUNBUFFERED=1: 標準出力/標準エラーをバッファリングせず CloudWatch にすぐ流す
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# アプリケーションの作業ディレクトリ
WORKDIR /app

# builderで構築した venv をそのままのパスでコピーする。
# venv 内のスクリプトは絶対パス（/app/.venv/bin/python）を参照するため、stage 間でパスを揃える必要がある
COPY --from=builder /app /app

# 仮想環境のパスを環境変数に追加
ENV PATH="/app/.venv/bin:$PATH"

# 実行スクリプト群をコピー
COPY inference/run.py inference/run.sample.py ./

# USE_REAL_INFERENCE=true のとき run.py を、false のとき run.sample.py を entry.py として配置
ARG USE_REAL_INFERENCE=false
RUN if [ "$USE_REAL_INFERENCE" = "true" ]; then cp run.py entry.py; else cp run.sample.py entry.py; fi

# 非rootユーザーを作成し、/app の所有権を付け替える
RUN useradd --create-home --uid 1000 app \
    && chown -R app:app /app

# 以降のプロセスは非rootユーザーで実行する
USER app

CMD ["python", "entry.py"]
