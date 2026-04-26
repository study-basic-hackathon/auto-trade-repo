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
docker compose up
```

すでにコンテナを起動済みの場合（依存パッケージの変更後など）はイメージを再ビルドする。

```bash
docker compose up --build
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

  