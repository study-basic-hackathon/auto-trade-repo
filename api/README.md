#Add line

# API 仕様書 (フロントエンド向け)

ダッシュボード等で利用できる API の一覧と使い方を、できるだけ平易にまとめています。

---

## 1. はじめに

### ベース URL

ブラウザから叩く URL は **すべて `/api/` で始まります**。たとえば本番なら `https://<ドメイン>/api/predictions/latest`、ローカル開発なら `http://localhost/api/predictions/latest` です。

```
本番:    https://<CloudFrontのドメイン>/api/...
ローカル: http://localhost/api/...
```

### レスポンスはすべて JSON

どのエンドポイントも JSON を返します。`fetch().then(res => res.json())` でそのままオブジェクトとして使えます。

### 共通のエラー

| HTTP ステータス | 意味 | フロント側の対応 |
|---|---|---|
| 200 | 正常 | レスポンスを使う |
| 404 | 該当データなし (例: 予測が1件もないとき) | 「データがまだありません」表示 |
| 422 | パラメータ不正 (例: `days=0`) | 値を見直す |
| 502 / 503 | バックエンド側の一時障害 | 「しばらく後に再読込」表示 |

---

## 2. エンドポイント一覧

| パス | 用途 | 使う場面 |
|---|---|---|
| `GET /api/predictions/latest` | **最新の予測 1 件** | ダッシュボード上部の「今日の予想」表示 |
| `GET /api/predictions?days=N` | **直近 N 日分の予測一覧** | 予測の推移チャート / 履歴テーブル |
| `GET /api/metrics/accuracy?days=N` | **過去 N 日間の的中率・誤差** | 「直近の的中履歴」「精度サマリー」表示 |
| `GET /api/adr/deviation` | **東証銘柄と ADR (米国上場) の乖離率** | 「主要企業 ADR 乖離」テーブル |
| `GET /api/getdaytradelist` | デイトレード注目銘柄 | 既存。注目銘柄テーブル |
| `GET /api/health` | 死活確認 | 通常は使わない (運用監視用) |
| `GET /api/sample/predictions` | サンプルデータ (旧形式) | 動作確認用。本番表示には使わないでください |

---

## 3. 各エンドポイント詳細

---

### 3.1 `GET /api/predictions/latest` — 最新の予測

最新の予測 (= 今朝08時に出た予測) を 1 件だけ返します。ダッシュボードの「今日のN225予想」カードに使えます。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `ticker` | 文字列 | 任意 | `n225` | 銘柄コード。現状は `n225` のみ対応 |

#### レスポンス例

```json
{
  "ticker": "n225",
  "prediction": {
    "target_date": "2026-05-01",
    "predicted_at": "2026-05-05T08:00:00+09:00",
    "model_version": "2026-05-01",
    "ticker": "n225",
    "prediction_sign": -1,
    "probability_up": 0.4753,
    "predicted_log_return": -0.00099,
    "predicted_return": -0.00099,
    "predicted_close": 59454.22,
    "current_close": 59513.12,
    "as_of_date": "2026-05-01"
  }
}
```

#### フィールドの意味
| フィールド | 説明 |
|---|---|
| `target_date` | 予測を行った日付 (= バッチが走った日) |
| `predicted_at` | 予測が実行された日時 (JST) |
| `model_version` | モデルのバージョン (学習日) |
| `prediction_sign` | **+1 = 上昇予想 / -1 = 下落予想** |
| `probability_up` | 上昇する確率 (0〜1)。0.5 が中立 |
| `predicted_close` | **次の取引日の予想終値 (円)** |
| `current_close` | 直近営業日の終値 (円) |
| `predicted_return` | 予想騰落率 (例: 0.005 = +0.5%) |
| `as_of_date` | 「直近営業日」(現在価格の基準日) |

#### JavaScript 使用例

```javascript
const res = await fetch("/api/predictions/latest");
if (!res.ok) {
  // 404 = まだ予測データがない
  showMessage("予測データがまだありません");
  return;
}
const data = await res.json();
const p = data.prediction;

document.getElementById("predicted-close").textContent = p.predicted_close.toLocaleString();
document.getElementById("direction").textContent = p.prediction_sign === 1 ? "▲ 上昇" : "▼ 下落";
document.getElementById("probability").textContent = (p.probability_up * 100).toFixed(1) + "%";
```

#### エラー
- データが 1 件もないとき → **HTTP 404**

---

### 3.2 `GET /api/predictions?days=N` — 直近の予測一覧

直近 N 日間の予測レコードを古い順 (古い→新しい) で返します。チャート描画や履歴一覧に使えます。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 範囲 | 説明 |
|---|---|---|---|---|---|
| `days` | 整数 | 任意 | `30` | 1〜730 | 何日前までさかのぼるか |
| `ticker` | 文字列 | 任意 | `n225` | - | 銘柄コード |

#### リクエスト例
```
GET /api/predictions?days=14
```

#### レスポンス例

```json
{
  "ticker": "n225",
  "window_days": 30,
  "from": "2026-04-05",
  "to": "2026-05-05",
  "count": 5,
  "items": [
    {
      "target_date": "2026-04-24",
      "predicted_at": "2026-05-05T00:13:28+09:00",
      "predicted_close": 59960.16,
      "current_close": 59716.18,
      "prediction_sign": 1,
      "probability_up": 0.6005,
      ...
    },
    {
      "target_date": "2026-04-27",
      ...
    },
    ...
  ]
}
```

#### フィールドの意味
| フィールド | 説明 |
|---|---|
| `window_days` | 集計対象期間 (= リクエスト時の `days`) |
| `from` / `to` | 集計対象の開始日 / 終了日 |
| `count` | 該当した予測件数 |
| `items` | 予測レコード配列 (古い順)。各要素は `/api/predictions/latest` の `prediction` と同じ形 |

#### JavaScript 使用例

```javascript
const res = await fetch("/api/predictions?days=14");
const data = await res.json();

// 例: チャート用に整形
const chartData = data.items.map(p => ({
  date: p.target_date,
  predicted: p.predicted_close,
  actual: p.current_close,
}));
```

---

### 3.3 `GET /api/metrics/accuracy?days=N` — 予測精度サマリー

過去 N 日間に出した予測のうち、**実績がすでに出ているもの** を集計して的中率や誤差を返します。「直近の的中履歴」「全体の精度カード」に使えます。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 範囲 | 説明 |
|---|---|---|---|---|---|
| `days` | 整数 | 任意 | `30` | 1〜730 | 集計期間 (日数) |
| `ticker` | 文字列 | 任意 | `n225` | - | 銘柄コード |

#### リクエスト例
```
GET /api/metrics/accuracy?days=14
```

#### レスポンス例

```json
{
  "ticker": "n225",
  "window_days": 30,
  "from": "2026-04-05",
  "to": "2026-05-05",
  "samples": 4,
  "direction_accuracy": 1.0,
  "mae": 539.45,
  "mape": 0.009016,
  "rmse": 545.85,
  "returns_r2": 0.2051,
  "by_date": [
    {
      "actual_target_date": "2026-04-27",
      "as_of_date": "2026-04-24",
      "predicted_close": 59960.16,
      "actual_close": 60537.36,
      "prediction_sign": 1,
      "actual_sign": 1,
      "hit": true,
      "abs_error": 577.20,
      "abs_pct_error": 0.009535
    },
    ...
  ]
}
```

#### フィールドの意味

**サマリー部 (集計結果)**

| フィールド | 説明 | 例 |
|---|---|---|
| `samples` | 集計対象になった予測の件数 | `4` |
| `direction_accuracy` | **方向 (上/下) の的中率** (0〜1) | `1.0` = 100% |
| `mae` | 平均絶対誤差 (円) | `539.45` 円ハズレ |
| `mape` | 平均絶対パーセント誤差 | `0.009016` = 約 0.9% |
| `rmse` | 二乗平均平方根誤差 (円) | `545.85` |
| `returns_r2` | 対数リターンの決定係数 R² (-∞〜1) | 1 に近いほど精度高 |

**`by_date` 配列 (1日 = 1要素)**

| フィールド | 説明 |
|---|---|
| `actual_target_date` | 予測対象だった営業日 |
| `as_of_date` | 予測時点での「直近営業日」 |
| `predicted_close` | 予想終値 (円) |
| `actual_close` | 実際の終値 (円) |
| `prediction_sign` | 予想方向 (+1=上昇 / -1=下落) |
| `actual_sign` | 実際の方向 (+1=上昇 / -1=下落) |
| `hit` | **方向が当たったか (true / false)** |
| `abs_error` | 円単位の絶対誤差 |
| `abs_pct_error` | パーセント単位の絶対誤差 (0.01 = 1%) |

#### JavaScript 使用例

```javascript
const res = await fetch("/api/metrics/accuracy?days=14");
const data = await res.json();

// 全体サマリー表示
document.getElementById("hit-rate").textContent = (data.direction_accuracy * 100).toFixed(1) + "%";
document.getElementById("avg-error").textContent = data.mae.toFixed(0) + " 円";

// 日別履歴テーブル
const tbody = document.getElementById("history-tbody");
data.by_date.forEach(row => {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${row.actual_target_date}</td>
    <td>${row.prediction_sign === 1 ? "▲ 陽線" : "▼ 陰線"}</td>
    <td>${row.actual_sign === 1 ? "▲ 陽線" : "▼ 陰線"}</td>
    <td>${row.hit ? "✓ 的中" : "✗ 外れ"}</td>
  `;
  tbody.appendChild(tr);
});
```

#### 注意点

- まだ評価可能なデータが無い場合は `samples: 0` で各指標が `null` になります。フロント側で「データがまだありません」表示にしてください。
- 予測してから1日経っていないものは `by_date` に含まれません (実績未確定のため)。

---

### 3.4 `GET /api/adr/deviation` — 東証銘柄と ADR の乖離率

東証に上場する日本企業について、対応する ADR (米国預託証券) との価格乖離率を返します。ダッシュボードの「主要企業 ADR 乖離」テーブルにそのまま使えます。

**乖離率の意味**: 円換算後の ADR 終値が東証終値より高ければプラス (= **米国市場で買われている = 翌営業日の東京で買い気配**)、マイナスなら売り気配の傾向。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `no_cache` | 真偽 | 任意 | `false` | `true` で強制再取得 (通常は不要) |

#### キャッシュ仕様
yfinance を内部で 12 回叩くため、初回は **約 5〜13 秒** かかります。レスポンスは **10 分間メモリにキャッシュ**され、2 回目以降は瞬時に返ります。

#### レスポンス例

```json
{
  "fetched_at": "2026-05-05T10:58:48+09:00",
  "usd_jpy": 157.211,
  "count": 11,
  "cached": false,
  "cache_age_seconds": 0,
  "items": [
    {
      "name": "トヨタ自動車",
      "tse_code": "7203",
      "adr": "TM",
      "us_exchange": "NYSE",
      "industry": "輸送用機器・自動車",
      "adr_shares_per_adr": 10.0,
      "tse_close": 3000.00,
      "adr_close_usd": 188.27,
      "adr_close_jpy": 2960.28,
      "deviation_pct": -1.32
    },
    ...
  ]
}
```

#### フィールドの意味

| フィールド | 説明 |
|---|---|
| `fetched_at` | 価格を取得した日時 (JST) |
| `usd_jpy` | 計算に使った USD/JPY レート |
| `count` | 銘柄件数 |
| `cached` | キャッシュからの応答か (true/false) |
| `cache_age_seconds` | キャッシュ生成からの経過秒数 |
| `items[].name` | 銘柄名 (日本語) |
| `items[].tse_code` | 東証銘柄コード (4桁、ゼロ埋め) |
| `items[].adr` | ADR ティッカー |
| `items[].us_exchange` | 米国取引所 (NYSE / NASDAQ など) |
| `items[].industry` | 業種 |
| `items[].adr_shares_per_adr` | 1 ADR が表す原株数 (例: 10 = 1ADR = 普通株10株) |
| `items[].tse_close` | 東証直近終値 (円) |
| `items[].adr_close_usd` | ADR 直近終値 (米ドル) |
| `items[].adr_close_jpy` | **ADR 終値の円換算** (= adr_close_usd × usd_jpy ÷ adr_shares_per_adr) |
| `items[].deviation_pct` | **乖離率 (%)** = (adr_close_jpy / tse_close - 1) × 100 |

価格取得に失敗した銘柄は `tse_close` / `adr_close_usd` / `adr_close_jpy` / `deviation_pct` が `null` になります。

#### JavaScript 使用例

```javascript
const res = await fetch("/api/adr/deviation");
const data = await res.json();

// 乖離率の絶対値で降順ソート、上位10件をテーブル表示
const sorted = data.items
  .filter(it => it.deviation_pct !== null)
  .sort((a, b) => Math.abs(b.deviation_pct) - Math.abs(a.deviation_pct))
  .slice(0, 10);

const tbody = document.getElementById("adr-tbody");
sorted.forEach(it => {
  const isUp = it.deviation_pct >= 0;
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${it.name}</td>
    <td>${it.tse_code}</td>
    <td>${it.tse_close.toLocaleString()}</td>
    <td>${it.adr_close_jpy.toLocaleString()}</td>
    <td class="${isUp ? 'up' : 'down'}">${isUp ? '▲' : '▼'} ${Math.abs(it.deviation_pct).toFixed(2)}%</td>
    <td>${isUp ? '▲ 買い気配' : '▼ 売り気配'}</td>
  `;
  tbody.appendChild(tr);
});
```

#### 注意点

- **初回呼び出しは10秒前後かかる**ことがあります。フロント側でローディング表示を出してください。同じセッションで2回目以降は瞬時に返ります。
- USD/JPY 取得に失敗すると **HTTP 502** を返します。
- マスタは `api/data/adr_master.json` で管理。銘柄追加/削除はバックエンド担当へ依頼してください。
- 一部銘柄 (例: ORIX) は ADR 上場廃止により `deviation_pct` が異常値になる可能性があります。マスタ調整中。

---

### 3.5 `GET /api/getdaytradelist` — デイトレード注目銘柄 (既存)

Yahoo!ファイナンスのランキングを集計して、売買代金 × 出来高増加率の両条件を満たす銘柄を返します。

#### クエリパラメータ
| パラメータ | 型 | デフォルト | 範囲 | 説明 |
|---|---|---|---|---|
| `pages` | 整数 | `10` | 1〜20 | 取得ページ数 (多いほど範囲が広い) |
| `min_trading_value` | 整数 | `1000000000` (10億円) | 0〜 | 売買代金の下限 |
| `min_volume_ratio` | 数値 | `2.0` | 0〜 | 出来高増加率の下限 (2.0 = 前日の2倍以上) |

#### レスポンス例

```json
{
  "count": 15,
  "pages": 10,
  "min_trading_value": 1000000000,
  "min_volume_ratio": 2.0,
  "items": [
    {
      "コード": "1234",
      "名称": "サンプル株式会社",
      "市場": "東証P",
      "取引値": 1234,
      "前日比": 56,
      "値上率(%)": 4.756,
      "売買代金": 12300000000,
      "出来高": 1234567,
      "出来高増加率": 3.45
    },
    ...
  ]
}
```

#### エラー
- Yahoo Finance に到達できないとき → HTTP 502

---

## 4. その他 (運用・確認用)

### `GET /api/health`
死活確認用。`{"status": "ok"}` を返します。

### `GET /api/sample/predictions`
**(非推奨)** 古いサンプルデータを返します。本物の予測は `/api/predictions/latest` などを使ってください。

---

## 5. ローカルでの動作確認

### 1. バックエンドが動いていることを確認

ターミナルで以下を叩いて `{"status":"ok"}` が返ればOK。
```bash
curl http://localhost/api/health
```

### 2. ブラウザで直接URLを叩く

ブラウザのアドレスバーに以下を入力するとJSONが見えます:
```
http://localhost/api/predictions/latest
http://localhost/api/predictions?days=14
http://localhost/api/metrics/accuracy?days=14
```

### 3. データが空のときの返り値を体験

`/api/predictions/latest` でまだデータがない期間 → HTTP 404 が返ります。フロントは404のときの表示を必ず実装してください。

---

## 6. よくある質問 (FAQ)

### Q. 予測値の `prediction_sign` が `1` と `-1` になっているのはなぜ？
A. 文字列 (`"up"` / `"down"`) ではなく数値で持っているのは、計算 (集計や符号反転) しやすくするためです。フロント表示時に `1 → "上昇"`、`-1 → "下落"` に変換してください。

### Q. `probability_up` が常に 0.5 付近なのはなぜ？
A. LSTM は「方向の確率」ではなく「対数リターン」を予測する回帰モデルです。`probability_up` は予測値を擬似的に確率化したもので、0.5 を中心に偏らない値になります。「方向だけ」を見るなら `prediction_sign` を使ってください。

### Q. `actual_target_date` と `as_of_date` と `target_date` の違いは？
A. 以下のように使い分けています:
- `target_date` (予測時): 予測バッチが走った日 (run.py の実行日)
- `as_of_date` (予測時): 予測の入力に使った直近営業日
- `actual_target_date` (評価時): 予測が当たったかを判定する基準日 (= as_of_date の次の営業日)

### Q. 月をまたいだら表示が変わる？
A. 内部的には月別ファイル (`predictions/n225.YYYY-MM.jsonl`) で保存していますが、API は月をまたいだ期間でも自動で複数ファイルを読んで結合します。フロント側で気にする必要はありません。

### Q. CORS エラーが出る
A. 同一オリジン (nginx 経由) なら出ません。別オリジンから叩く場合はバックエンド担当に相談してください。
