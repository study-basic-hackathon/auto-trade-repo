# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## コマンド

### ローカル開発環境

```bash
# 初回: .env を作成
cp .env.example .env

# コンテナ起動
docker compose up

# 依存パッケージ変更後は再ビルド
docker compose up --build
```

### Python (api/)

パッケージ管理は `uv` を使用。

```bash
cd api
uv sync              # 依存パッケージのインストール
uv add <package>     # パッケージ追加
```

## アーキテクチャ

### ローカル構成

`compose.yaml` で 3 コンテナを起動する。

| コンテナ | ポート | 役割 |
|---|---|---|
| nginx | 80 | リバースプロキシ + 静的ファイル配信 |
| api | 8080 | FastAPI バックエンド |
| minio | 9000 / 9001 | S3 互換ストレージ（ローカル専用） |

nginx が `/api/*` を `http://api:8080` に転送し、それ以外は `front/` 以下の HTML を返す。

### 本番構成（AWS）

```
ブラウザ → CloudFront → Internal ALB → ECS Fargate タスク
                                           ├── nginx コンテナ (port 80)
                                           └── fastapi コンテナ (port 8080)
                                                    ↓ Gateway VPC Endpoint
                                                   S3
```

ECS タスクはプライベートサブネットのみ。インターネットへの直接経路なし（NAT Gateway なし）。

### S3 バケット構成

```
{S3_BUCKET_NAME}/
├── predictions/{ticker}.jsonl   # 予測結果（1行1JSON）
└── models/{ticker}.{version}.onnx
```

JSONL の 1 行スキーマ:
```json
{
  "target_date": "2026-04-27",
  "predicted_at": "2026-04-27T08:00:00+09:00",
  "model_version": "2026-04-01",
  "ticker": "n225",
  "prediction_sign": 1,
  "probability_up": 0.62
}
```

### API エンドポイント（api/main.py）

| パス | 説明 |
|---|---|
| `GET /api/health` | ヘルスチェック |
| `GET /api/getdaytradelist` | Yahoo Finance から売買代金・出来高増加率ランキングを取得・結合して返す |
| `GET /api/sample/predictions` | S3 の `predictions/n225.jsonl` を読み込んで返す |

## 環境変数

| 変数 | 説明 |
|---|---|
| `S3_BUCKET_NAME` | S3 バケット名 |
| `ENDPOINT_URL` | S3 エンドポイント（ローカルでは `http://minio:9000`） |
| `ACCESS_KEY` / `SECRET_KEY` | S3 認証情報（ローカルでは `minioadmin`） |

## MinIO（ローカル S3）

- Web コンソール: http://localhost:9001（ユーザー名/パスワード: `minioadmin`）
- バケット作成後、`.env` の `S3_BUCKET_NAME` と同じ名前で作成すること
- サンプルデータ: `samples/predictions/n225.jsonl` → バケットの `predictions/` にアップロード

## Terraform

### モジュール構成

`infra/terraform/envs/prod/main.tf` が以下のモジュールを全て呼び出す単一レイヤー構成。

| モジュール | 役割 |
|---|---|
| `modules/network` | VPC・サブネット・SG・VPC Endpoint |
| `modules/s3` | 予測結果・モデル用 S3 バケット |
| `modules/ecr` | nginx・api・inference の ECR リポジトリ |
| `modules/oidc` | GitHub Actions OIDC 認証用 IAM ロール |
| `modules/app` | ALB・ECS Fargate・CloudFront |
| `modules/inference` | 推論バッチ（ECS タスク定義 + EventBridge スケジューラ） |

### 初回デプロイ順序

ECR が存在しないと GitHub Actions がイメージを push できないため、`-target` で順序を制御する。

```bash
# 1. ECR と OIDC だけ先に apply
terraform apply -target=module.ecr -target=module.oidc

# 2. output の github_actions_role_arn を GitHub Repository Variables（AWS_OIDC_ROLE_ARN）に設定

# 3. develop → main の PR をマージ → GitHub Actions が ECR にイメージを push

# 4. terraform.tfvars の nginx_image_uri / api_image_uri / inference_image_uri を実際の ECR URI に更新して全体 apply
terraform apply
```

### GitHub Actions

| ワークフロー | トリガー | 内容 |
|---|---|---|
| `.github/workflows/ci.yml` | PR → develop または develop → main PR | Dockerfile を Hadolint で lint |
| `.github/workflows/cd-ecr.yml` | develop → main PR のマージ | nginx・api・inference イメージをビルドして ECR に push |

CD に必要な GitHub Repository Variables（Settings → Secrets and variables → Actions → Variables）:

| Variable 名 | 値 |
|---|---|
| `AWS_OIDC_ROLE_ARN` | `terraform output github_actions_role_arn` の出力値 |
| `AWS_REGION` | `ap-northeast-1` |
| `USE_REAL_INFERENCE` | `false`（サンプル）/ `true`（本番） |

## 推論コンテナ（inference）

`docker compose` には含まれず、`docker run` で単発実行するバッチコンテナ。

### 実行スクリプトの切り替え

ビルド引数 `USE_REAL_INFERENCE` で `entry.py`（コンテナ内で実行されるスクリプト）を切り替える。

| `USE_REAL_INFERENCE` | 使用されるスクリプト |
|---|---|
| `false`（デフォルト） | `run.sample.py` |
| `true` | `run.py` |

ローカルでのビルド:

```bash
# run.sample.py を使う（デフォルト）
docker build -f infra/docker/inference/Dockerfile -t inference .

# run.py を使う
docker build --build-arg USE_REAL_INFERENCE=true -f infra/docker/inference/Dockerfile -t inference .
```

GitHub Actions では `USE_REAL_INFERENCE` Variable の値が自動的に渡される。
