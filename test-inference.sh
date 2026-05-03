#!/bin/bash
# inferenceコンテナのローカルテスト実行スクリプト
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_YEAR=$(date +%Y)
IMAGE_NAME="inference-local"

usage() {
    cat <<EOF
使用方法: $(basename "$0") [オプション] <日付> [<日付> ...]

説明:
  inferenceコンテナをローカルでテスト実行します。
  事前に 'docker compose up' でMinIOが起動している必要があります。

日付形式:
  yyyymmdd          8桁指定  例: 20260501
  mmdd              4桁指定  例: 0501（現在年 ${CURRENT_YEAR} で補完）
  mmdd-mmdd         4桁範囲  例: 0501-0510
  yyyymmdd-yyyymmdd 8桁範囲  例: 20260501-20260510

組み合わせ例:
  $(basename "$0") 0501
  $(basename "$0") 0501 0503 0507
  $(basename "$0") 0501-0510
  $(basename "$0") 0501-0510 0515 0520-0525
  $(basename "$0") 20260501 0503-0510

オプション:
  --build    イメージを強制再ビルドする
  --real     USE_REAL_INFERENCE=true でビルドする（デフォルト: false）
  -h, --help このヘルプを表示する
EOF
    exit 0
}

# mmdd または yyyymmdd を YYYY-MM-DD に変換
parse_single_date() {
    local raw="$1"
    case ${#raw} in
        4)
            echo "${CURRENT_YEAR}-${raw:0:2}-${raw:2:2}"
            ;;
        8)
            echo "${raw:0:4}-${raw:4:2}-${raw:6:2}"
            ;;
        *)
            echo "エラー: 不正な日付形式: '$raw'（4桁または8桁の数字を指定してください）" >&2
            exit 1
            ;;
    esac
}

# YYYY-MM-DD を Unix タイムスタンプに変換（macOS 対応）
date_to_ts() {
    date -j -f "%Y-%m-%d" "$1" +%s
}

# YYYY-MM-DD の日付を1日進める（macOS 対応）
next_date() {
    date -j -v+1d -f "%Y-%m-%d" "$1" +"%Y-%m-%d"
}

# 日付範囲を YYYY-MM-DD のリストに展開
expand_date_range() {
    local start end
    start=$(parse_single_date "$1")
    end=$(parse_single_date "$2")

    local ts_start ts_end
    ts_start=$(date_to_ts "$start")
    ts_end=$(date_to_ts "$end")

    if [ "$ts_start" -gt "$ts_end" ]; then
        echo "エラー: 範囲の終了日が開始日より前です: '$1'（${start}）→ '$2'（${end}）" >&2
        exit 1
    fi

    local current="$start"
    while [ "$(date_to_ts "$current")" -le "$ts_end" ]; do
        echo "$current"
        current=$(next_date "$current")
    done
}

# MinIO コンテナが属するネットワーク名を自動取得
get_compose_network() {
    local minio_id
    minio_id=$(cd "$REPO_ROOT" && docker compose ps -q minio 2>/dev/null || true)
    if [ -n "$minio_id" ]; then
        docker inspect "$minio_id" \
            --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' \
            2>/dev/null | awk '{print $1}'
    fi
}

# ---- 引数解析 ----

[ $# -eq 0 ] && usage

BUILD=false
USE_REAL=false
DATE_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --build)   BUILD=true ;;
        --real)    USE_REAL=true ;;
        -h|--help) usage ;;
        -*)
            echo "エラー: 不明なオプション: '$1'" >&2
            usage
            ;;
        *) DATE_ARGS+=("$1") ;;
    esac
    shift
done

if [ ${#DATE_ARGS[@]} -eq 0 ]; then
    echo "エラー: 日付を1つ以上指定してください" >&2
    usage
fi

# ---- 日付リスト生成 ----

TARGET_DATES=()

for arg in "${DATE_ARGS[@]}"; do
    if [[ "$arg" =~ ^([0-9]{4})-([0-9]{4})$ ]]; then
        # mmdd-mmdd
        while IFS= read -r d; do
            TARGET_DATES+=("$d")
        done < <(expand_date_range "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}")
    elif [[ "$arg" =~ ^([0-9]{8})-([0-9]{8})$ ]]; then
        # yyyymmdd-yyyymmdd
        while IFS= read -r d; do
            TARGET_DATES+=("$d")
        done < <(expand_date_range "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}")
    elif [[ "$arg" =~ ^[0-9]{4}$ ]] || [[ "$arg" =~ ^[0-9]{8}$ ]]; then
        TARGET_DATES+=("$(parse_single_date "$arg")")
    else
        echo "エラー: 不正な引数: '$arg'" >&2
        echo "  mmdd / yyyymmdd / mmdd-mmdd / yyyymmdd-yyyymmdd の形式で指定してください" >&2
        exit 1
    fi
done

echo "対象日付（${#TARGET_DATES[@]} 件）:"
for d in "${TARGET_DATES[@]}"; do
    echo "  - $d"
done

# ---- 環境変数の準備 ----

# .env から S3_BUCKET_NAME などを読み込む
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

S3_BUCKET_NAME="${S3_BUCKET_NAME:-auto-trade-repo-123456789012-ap-northeast-1-an}"
# inferenceコンテナはComposeネットワーク内でminioにアクセスする
ENDPOINT_URL="http://minio:9000"
ACCESS_KEY="${ACCESS_KEY:-minioadmin}"
SECRET_KEY="${SECRET_KEY:-minioadmin}"

# ---- Compose ネットワーク確認 ----

COMPOSE_NETWORK=$(get_compose_network)

if [ -z "$COMPOSE_NETWORK" ]; then
    echo "" >&2
    echo "エラー: MinIOコンテナが起動していません。" >&2
    echo "       先に 'docker compose up' を実行してください。" >&2
    exit 1
fi

echo "使用ネットワーク: $COMPOSE_NETWORK"

# ---- イメージビルド ----

if $BUILD || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo ""
    echo "イメージをビルドします: $IMAGE_NAME"
    BUILD_ARGS=()
    if $USE_REAL; then
        BUILD_ARGS+=(--build-arg USE_REAL_INFERENCE=true)
    fi
    docker build ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} \
        -f "$REPO_ROOT/infra/docker/inference/Dockerfile" \
        -t "$IMAGE_NAME" \
        "$REPO_ROOT"
fi

# ---- 推論実行 ----

SUCCESS_COUNT=0
FAILURE_COUNT=0
FAILED_DATES=()

for target_date in "${TARGET_DATES[@]}"; do
    echo ""
    echo "=== 推論実行: $target_date ==="
    if docker run --rm \
        --network "$COMPOSE_NETWORK" \
        -e TARGET_DATE="$target_date" \
        -e S3_BUCKET_NAME="$S3_BUCKET_NAME" \
        -e ENDPOINT_URL="$ENDPOINT_URL" \
        -e ACCESS_KEY="$ACCESS_KEY" \
        -e SECRET_KEY="$SECRET_KEY" \
        "$IMAGE_NAME"; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        echo "  失敗: $target_date" >&2
        FAILURE_COUNT=$((FAILURE_COUNT + 1))
        FAILED_DATES+=("$target_date")
    fi
done

echo ""
echo "=============================="
echo "完了: 成功 ${SUCCESS_COUNT} 件 / 失敗 ${FAILURE_COUNT} 件"
if [ ${#FAILED_DATES[@]} -gt 0 ]; then
    echo "失敗した日付:"
    for d in "${FAILED_DATES[@]}"; do
        echo "  - $d"
    done
fi
echo "=============================="

[ "$FAILURE_COUNT" -eq 0 ]
