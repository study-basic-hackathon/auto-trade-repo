# 日経225予測サービス インフラ要件定義書

## 1. プロジェクト概要

ハッカソン向けPoC。日経225関連銘柄の翌営業日株価予測値を、Webブラウザから閲覧できるサービス。バックエンドは事前にバッチ処理で生成された予測結果（S3に保存）を返却するシンプルなREST APIを提供する。

**スコープ外（今回は構築しない）**
- 機械学習モデルの学習バッチ
- 日次推論バッチ（予測結果JSONLの生成処理）
- ユーザー認証・認可
- WAF、Shield Advanced
- 独自ドメイン取得とACM証明書発行
- 予測精度モニタリング

上記は手動またはローカルで実行し、生成された`.jsonl`/`.pkl`ファイルをS3に手動アップロードする運用とする。

## 2. アーキテクチャ全体図

```
[ユーザーのブラウザ]
        ↓ HTTPS（CloudFrontデフォルト証明書）
[CloudFront Distribution]
        ↓ VPC Origins経由（AWSネットワーク内、ENI経由）
[Internal ALB（プライベートサブネット）]
        ↓ HTTP
[ECS Fargate Task（プライベートサブネット）]
   ├── nginx コンテナ（port 80）
   │     ・Reactビルド成果物を静的配信
   │     ・/api/* を localhost:8000 にリバプロ
   └── fastapi コンテナ（port 8000、内部のみ）
          ↓ Gateway VPC Endpoint
       [S3バケット: predictions/, models/]
```

## 3. AWSリソース要件

### 3.1 リージョン・命名規則

- **リージョン**: ap-northeast-1（東京）
- **プロジェクト名プレフィックス**: `auto-trade-repo`（必要に応じて変更可）
- 全リソースに以下のタグを付与
  - `Repository = auto-trade-repo`
  - `Environment = prod`

### 3.2 VPC・ネットワーク

- **VPC**: 新規作成、CIDR `10.0.0.0/16`
- **サブネット構成**: マルチAZ（ap-northeast-1a と ap-northeast-1c）
  - **プライベートサブネット × 2**: ALB、ECS Task、VPC Origin用
    - `10.0.1.0/24`（1a）、`10.0.2.0/24`（1c）
  - パブリックサブネットは不要（NAT Gatewayもなし）
- **Internet Gateway**: 不要
- **NAT Gateway**: 不要（後述のVPC Endpointで代替）

### 3.3 VPC Endpoints

ECS FargateがプライベートサブネットからAWS各サービスへアクセスするため、以下のVPC Endpointを作成する。

| サービス | タイプ | 用途 |
|---|---|---|
| S3 | Gateway | 予測結果JSONLの取得（無料） |
| ECR API | Interface | Dockerイメージpull時のAPI呼び出し |
| ECR DKR | Interface | Dockerイメージレイヤーpull |
| CloudWatch Logs | Interface | コンテナログ送信 |

- Gateway Endpoint（S3）はプライベートサブネットのルートテーブルに関連付ける
- Interface Endpointは両AZのプライベートサブネットに配置し、Private DNSを有効化
- Interface EndpointのSecurity Groupは、ECSタスクのSecurity GroupからのHTTPS（443）を許可

### 3.4 ECS（Fargate）

- **クラスタ**: `auto-trade-repo-cluster`
- **起動タイプ**: Fargate
- **タスク定義**: `auto-trade-repo-task`
  - **CPU/メモリ**: 0.5 vCPU / 1 GB（コスト最小構成）
  - **ネットワークモード**: awsvpc
  - **タスク実行ロール（Task Execution Role）**: ECRからのpull、CloudWatch Logsへの書き込み権限（AWS管理ポリシー `AmazonECSTaskExecutionRolePolicy`）
  - **タスクロール（Task Role）**: 後述のIAMポリシーを付与
  - **コンテナ定義**: 後述のサイドカー2コンテナ
- **サービス**: `auto-trade-repo-service`
  - **デサイアードカウント**: 1
  - **配置**: プライベートサブネット × 2
  - **Security Group**: ALBのSGからのHTTP（80）のみ許可
  - **ALBターゲットグループ**: nginxコンテナのport 80をターゲット

### 3.5 コンテナ定義（サイドカー構成）

#### コンテナ1: nginx（フロントエンド + リバプロ）

- **イメージ**: ECRに格納したカスタムnginxイメージ（Reactビルド成果物を内包）
- **ポート**: 80（公開）
- **ボリューム/マウント**: 不要
- **環境変数**: 不要
- **CloudWatch Logs**: ロググループ `/ecs/auto-trade-repo/nginx`、保持期間7日

**Dockerfile**
infra/docker/nginx/Dockerfileを参照

#### コンテナ2: fastapi（バックエンドAPI）

- **イメージ**: ECRに格納したPythonアプリイメージ
- **ポート**: 8000（コンテナ内のみ、公開しない）
- **環境変数**:
  - `S3_BUCKET_NAME`: 予測結果S3バケット名
  - `AWS_REGION`: `ap-northeast-1`
  - `DEFAULT_TICKER`: `n225`（デフォルト銘柄）
- **CloudWatch Logs**: ロググループ `/ecs/auto-trade-repo/fastapi`、保持期間7日

**Dockerfile**
infra/docker/fastapi/Dockerfileを参照

### 3.6 ALB（Application Load Balancer）

- **名称**: `auto-trade-repo-alb`
- **スキーム**: **internal**（インターネット非公開）
- **配置**: プライベートサブネット × 2
- **リスナー**: HTTP（80）のみ
  - HTTPSリスナーは不要（CloudFrontがTLS終端を担う）
- **ターゲットグループ**: `auto-trade-repo-tg`
  - ターゲットタイプ: ip（Fargate要件）
  - プロトコル/ポート: HTTP/80
  - **ヘルスチェック**: `GET /api/health`、ステータスコード200を期待
- **Security Group**: CloudFront VPC OriginのENIからのHTTP（80）のみ許可

### 3.7 CloudFront（VPC Origin）

- **Distribution**: `auto-trade-repo-distribution`
- **Origin**: VPC Origin
  - **ターゲット**: 上記Internal ALBのARN
  - **プロトコル**: HTTP（80）
- **Viewer Protocol Policy**: Redirect HTTP to HTTPS
- **デフォルト証明書**: CloudFrontのデフォルト証明書（`*.cloudfront.net`、自動TLS）
- **キャッシュビヘイビア**:
  - **Default behavior（`/*`）**: 静的アセット用、デフォルトキャッシュポリシー（`Managed-CachingOptimized`）
  - **`/api/*`**: APIレスポンスはキャッシュしない（`Managed-CachingDisabled`ポリシー、`Managed-AllViewer`オリジンリクエストポリシー）
- **HTTPメソッド許可**: GET, HEAD, OPTIONS（API用にPOST等が必要なら追加）

### 3.8 S3

- **バケット名**: `auto-trade-repo-[アカウントID]-[リージョン]-an`
- **リージョン**: ap-northeast-1
- **パブリックアクセス**: ブロック有効（VPC Endpoint経由でのみアクセス）
- **バージョニング**: 不要
- **暗号化**: SSE-S3（デフォルト）
- **キー構造**:
  ```
  s3://{bucket}/
  ├── predictions/
  │   ├── n225.jsonl       # 日経225指数の予測履歴
  │   ├── 1617.jsonl       # TOPIX-17 食品（配当込み）
  │   └── ...              # 他銘柄（追加予定）
  └── models/
      ├── n225.2026-04-01.onnx
      ├── 1617.2026-04-01.onnx
      ├── 1617.2026-04-25.onnx
      └── {ticker}.{version}.onnx

  ```
- **JSONLの1行スキーマ（FastAPIが返却するレスポンスと同一構造）**:
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

### 3.9 IAM

#### Task Execution Role
- AWS管理ポリシー `AmazonECSTaskExecutionRolePolicy` をアタッチ

#### Task Role（fastapiコンテナがS3にアクセスするため）
- カスタムポリシー、以下のActionを許可:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        "Resource": [
          "arn:aws:s3:::{bucket-name}",
          "arn:aws:s3:::{bucket-name}/predictions/*"
        ]
      }
    ]
  }
  ```

### 3.10 ECR

- リポジトリ × 2:
  - `auto-trade-repo/nginx`
  - `auto-trade-repo/api`
- イメージスキャン: オン（プッシュ時）
- ライフサイクルポリシー: 直近5イメージのみ保持

## 4. アプリケーション仕様（参考）

インフラの設計を確定させるための参考情報。実装はバックエンド担当が行う。

### 4.1 FastAPIのエンドポイント

| メソッド | パス | クエリパラメータ | 説明 |
|---|---|---|---|
| GET | `/api/health` | なし | ヘルスチェック。`{"status": "ok"}`を返却 |
| GET | `/api/predictions` | `ticker`（任意、デフォルト=`n225`）<br>`date`（任意、デフォルト=本日） | 指定銘柄・指定日の予測値を返却 |
（その他バックエンドにお任せ）

### 4.2 リクエスト・レスポンス例

**リクエスト**: `GET /api/predictions?ticker=n225&date=2026-04-27`

**レスポンス**:
```json
{
  "target_date": "2026-04-27",
  "predicted_at": "2026-04-27T08:00:00+09:00",
  "model_version": "2026-04-01",
  "ticker": "n225",
  "prediction_sign": 1,
  "probability_up": 0.58
}
```

**実装メモ（バックエンド向け）**:
- S3から`predictions/{ticker}.jsonl`を取得し、`target_date`が一致する行をフィルタして返す
- 該当データなしの場合は404を返却
- リクエストの都度S3にアクセスする方針（ハッカソン規模ではキャッシュ不要）

## 5. ロギング方針

| 対象 | 出力先 | 保持期間 |
|---|---|---|
| nginxアクセスログ・エラーログ | CloudWatch Logs `/ecs/n225-predictor/nginx` | 7日 |
| FastAPIログ | CloudWatch Logs `/ecs/n225-predictor/fastapi` | 7日 |
| ALBアクセスログ | CloudWatch Logs `/ecs/n225-predictor/alb` | 7日 |
| CloudFrontアクセスログ | CloudWatch Logs `/ecs/n225-predictor/cloudfront` | 7日 |
| S3アクセスログ | 出力しない | - |

ハッカソン期間中のデバッグに使えればよく、長期保存・分析用途は考慮しない。

## 6. デプロイ手順（IaC実装者向けの想定フロー）

1. **基盤リソース作成**: VPC、サブネット、Security Group、VPC Endpoints、IAM、S3、ECR
2. **手動操作**: ローカルで`docker build`し、ECRにイメージをpush
3. **アプリケーションリソース作成**: ECS Cluster、Task Definition、ALB、Target Group、ECS Service
4. **CloudFront作成**: VPC Originを指定したDistribution
5. **動作確認**: CloudFrontのドメイン（`*.cloudfront.net`）にブラウザでアクセス

## 7. IaCツールの選定

Terraform

## 8. 推定コスト感

ハッカソン期間中の連続稼働を想定した概算。

| リソース | 月額換算 |
|---|---|
| ECS Fargate（0.5vCPU/1GB常時稼働） | 約$15 |
| Internal ALB | 約$22 |
| Interface VPC Endpoints × 3 | 約$22 |
| CloudFront | 転送量次第（PoCなら$1未満） |
| S3 | ほぼ無料 |
| **合計** | **約$60/月** |

ハッカソン終了後は速やかにECS Service desired count=0、Distribution無効化、ALB削除を推奨。
