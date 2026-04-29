# 自動売買でがっぽがっぽ

## ローカルでの開発

### 初回セットアップ

`.env.example` をコピーして `.env` を作成する。

```bash
cp .env.example .env
```

必要に応じて `.env` を編集する（バケット名など）。

```env
S3_BUCKET_NAME=auto-trade-repo-123456789012-ap-northeast-1-an
```

コンテナを起動する。

```bash
docker compose up -d
```

すでにコンテナを起動済みの場合（依存パッケージの変更後など）はイメージを再ビルドする。

```bash
docker compose up -d --build
```

localhostでアクセスできる。

* http://localhost/api/* → Python (FastAPI)
* 上記以外 → HTMLファイルを返却

### MinIO（S3互換ストレージ）

ローカル開発では本番のS3の代わりにMinIOコンテナを使用する。

| 用途 | URL |
|---|---|
| S3互換APIエンドポイント | http://localhost:9000 |
| Webコンソール | http://localhost:9001 |

**Webコンソールへのログイン**

| 項目 | 値 |
|---|---|
| ユーザー名 | minioadmin |
| パスワード | minioadmin |

**バケットの作成**

1. Webコンソール（http://localhost:9001）にログイン
2. 左メニューの「Buckets」→「Create Bucket」をクリック
3. Bucket Name に `.env` の `S3_BUCKET_NAME` と同じ値を入力して「Create Bucket」をクリック

**バケット・フォルダ構成**

`S3_BUCKET_NAME` で指定したバケットに以下の構成でファイルを配置する。

```
{バケット名}/
├── predictions/
│   └── n225.jsonl
└── models/
    └── {ticker}.{version}.onnx
```

サンプルの `n225.jsonl` は `samples/predictions/n225.jsonl` にある。Webコンソールの `predictions/` フォルダにアップロードして使用する。

## AWSインフラデプロイ

### 前提条件

- Terraform >= 1.10
- AWS CLI（`aws configure` で認証済み）
- tfstate 用 S3 バケットが作成済み（`tfstate-{ACCOUNT_ID}-ap-northeast-1-an`）

### 初回セットアップ

```bash
cd infra/terraform/envs/prod

# terraform.tfvars を作成
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars を編集して github_org などを設定
```

```bash
# 初期化（バケット名は実際のアカウントIDに置き換える）
terraform init -backend-config="bucket=tfstate-{ACCOUNT_ID}-ap-northeast-1-an"
```

### 初回デプロイ手順

ECR が存在しないと GitHub Actions がイメージを push できないため、最初に ECR と OIDC だけを先に apply する。

**Step 1: ECR・OIDC を先に apply**

```bash
terraform apply -target=module.ecr -target=module.oidc
```

**Step 2: GitHub Secrets を設定**

| Secret 名 | 設定する値 |
|---|---|
| `AWS_OIDC_ROLE_ARN` | `terraform output github_actions_role_arn` の出力値 |
| `AWS_REGION` | `ap-northeast-1` |

**Step 3: main ブランチに push → GitHub Actions が ECR にイメージを自動登録**

**Step 4: `terraform.tfvars` のイメージ URI を ECR の実際の URL に更新**

```
nginx_image_uri = "{ACCOUNT_ID}.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/nginx:latest"
api_image_uri   = "{ACCOUNT_ID}.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/api:latest"
```

**Step 5: 全体 apply**

```bash
terraform apply
```

### 2回目以降

コードを変更して main に push すると GitHub Actions が自動で ECR にイメージを push する。ECS タスク定義の更新は別途 `terraform apply` が必要。

---

### 推論コンテナ（inference）

推論コンテナはS3からモデルを取得して推論を実行し、結果を `predictions/{ticker}.jsonl` に追記して終了する。

**イメージのビルド**

```bash
docker build -f infra/docker/inference/Dockerfile -t inference .
```

**実行スクリプトについて**

| ファイル | 用途 |
|---|---|
| `run.py` | 本番用。推論ロジックはここに実装する。Dockerfile の `CMD` で実行される。 |
| `run.sample.py` | 動作確認用のサンプル実装。イメージには含まれない。 |

推論ロジックを実装する場合は `run.py` を編集すること。`run.sample.py` は参考実装であり、変更する必要はない。

**本番想定の実行コマンド（1日分）**

環境変数 `TARGET_DATE` で推論対象日付を指定する。省略すると今日（JST）が使われる。

```bash
docker run --rm --network auto-trade-repo_default -e S3_BUCKET_NAME=auto-trade-repo-123456789012-ap-northeast-1-an -e ENDPOINT_URL=http://minio:9000 -e ACCESS_KEY=minioadmin -e SECRET_KEY=minioadmin -e TARGET_DATE=2026-04-27 inference
```

**動作確認用（run.sample.py を使う場合）**

`-v` でホストの `run.sample.py` をコンテナにマウントし、末尾のコマンドで上書き実行する。

```bash
docker run --rm --network auto-trade-repo_default -v $(pwd)/inference/run.sample.py:/app/run.sample.py -e S3_BUCKET_NAME=auto-trade-repo-123456789012-ap-northeast-1-an -e ENDPOINT_URL=http://minio:9000 -e ACCESS_KEY=minioadmin -e SECRET_KEY=minioadmin -e TARGET_DATE=2026-04-27 inference python run.sample.py
```

**動作確認用（日付範囲のループ）**

以下は4月1日〜5月31日の全日付分を連続実行する例。

```bash
python3 -c "from datetime import date,timedelta; d,e=date(2026,4,1),date(2026,5,31); [print(d+timedelta(i)) for i in range((e-d).days+1)]" | while read d; do docker run --rm --network auto-trade-repo_default -v $(pwd)/inference/run.sample.py:/app/run.sample.py -e S3_BUCKET_NAME=auto-trade-repo-123456789012-ap-northeast-1-an -e ENDPOINT_URL=http://minio:9000 -e ACCESS_KEY=minioadmin -e SECRET_KEY=minioadmin -e TARGET_DATE="$d" inference python run.sample.py; done
```
