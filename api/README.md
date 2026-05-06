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
| `GET /api/predictions/explanation/latest` | **特徴量の寄与 (相関係数)** | 「予想根拠」棒グラフ |
| `GET /api/metrics/accuracy?days=N` | **過去 N 日間の的中率・誤差** | 「直近の的中履歴」「精度サマリー」表示 |
| `GET /api/adr/deviation` | **東証銘柄と ADR (米国上場) の乖離率** | 「主要企業 ADR 乖離」テーブル |
| `GET /api/markets/us` | **NYダウ / NASDAQ / S&P500 / USD/JPY の前日終値** | 「米国マーケット (前日終値)」カード |
| `GET /api/markets/polymarket` | **Polymarket 予想市場のセンチメント11件** | 「マーケット予想・センチメントカード」 |
| `GET /api/markets/pts/overnight` | **PTSナイト 売買代金 TOP15 + TSE乖離** | 「翌朝寄付き要注目銘柄」カード |
| `GET /api/markets/pts/premarket` | **PTSデイ 売買代金 TOP15 + GAP予想** | 「寄付きGAP候補」カード (朝8:50頃利用) |
| `GET /api/markets/pts/volume_surge` | **PTS出来高 vs TSE30日平均 比率** | 「異常出来高検知」アラート |
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

### 3.3 `GET /api/predictions/explanation/latest` — 予想根拠 (特徴量の寄与)

最新の予測について、各特徴量と「N225 翌日リターン」の **過去60営業日のピアソン相関係数** を返します。ダッシュボードの「予想根拠 (特徴量の寄与)」棒グラフにそのまま使えます。

> ⚠️ **注意**: これは「相関係数による参考指標」であって、機械学習モデル (LSTM) の本物の SHAP 値ではありません。教育・参考目的でお使いください。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `ticker` | 文字列 | 任意 | `n225` | 銘柄コード |

#### レスポンス例

```json
{
  "ticker": "n225",
  "explanation": {
    "computed_at": "2026-05-05T15:32:44+09:00",
    "as_of_date": "2026-05-01",
    "ticker": "n225",
    "method": "pearson_correlation",
    "lookback_days": 60,
    "samples": 60,
    "features": [
      { "name": "S&P500 前日変化率",       "symbol": "^GSPC", "contribution":  0.5039, "samples": 60 },
      { "name": "NASDAQ 前日変化率",        "symbol": "^IXIC", "contribution":  0.4830, "samples": 60 },
      { "name": "VIX 前日変化率",           "symbol": "^VIX",  "contribution": -0.4545, "samples": 60 },
      { "name": "NYダウ 前日変化率",        "symbol": "^DJI",  "contribution":  0.4424, "samples": 60 },
      { "name": "原油(WTI) 前日変化率",     "symbol": "CL=F",  "contribution": -0.2142, "samples": 60 },
      ...
    ]
  }
}
```

`features` 配列は **寄与の絶対値が大きい順** で並びます (上位ほど影響が大きい)。

#### フィールドの意味

| フィールド | 説明 |
|---|---|
| `computed_at` | 計算日時 (JST) |
| `as_of_date` | 計算時点での「直近営業日」 |
| `method` | 計算手法 (常に `pearson_correlation`) |
| `lookback_days` | 相関計算に使った過去営業日数 |
| `samples` | 全特徴量で利用できた最大サンプル数 |
| `features[].name` | 特徴量名 (日本語) |
| `features[].symbol` | yfinance シンボル |
| `features[].contribution` | **相関係数 (-1 〜 +1)**。正なら順相関 (上がると N225 上昇)、負なら逆相関 |
| `features[].samples` | この特徴量で実際に使えたサンプル数 (yfinance 取得失敗で減ることあり) |

`contribution` が `null` の場合は、データ不足や全期間 NaN で計算不能。

#### JavaScript 使用例

```javascript
const res = await fetch("/api/predictions/explanation/latest");
if (!res.ok) {
  showMessage("予想根拠データがまだありません");
  return;
}
const data = await res.json();
const features = data.explanation.features;

// 棒グラフを描画 (絶対値が大きい順、正=赤、負=青)
const max = Math.max(...features.map(f => Math.abs(f.contribution || 0)));
features.forEach(f => {
  const c = f.contribution;
  if (c === null) return;
  const bar = document.createElement("div");
  bar.className = "feature-bar " + (c >= 0 ? "positive" : "negative");
  bar.style.width = (Math.abs(c) / max * 100) + "%";
  bar.textContent = `${f.name}: ${c >= 0 ? "+" : ""}${c.toFixed(2)}`;
  chartContainer.appendChild(bar);
});
```

#### 注意点

- 相関係数なので **値の絶対値は大きくても 0.5〜0.7 程度** に収まることが多いです。
- LSTM モデルの「本物の予測根拠」ではありません。あくまで「相関の高い特徴量を可視化する参考指標」です。
- 推論バッチが走るたびに最新の数字が更新されます (平日 08:00 JST)。
- 一部の銘柄が yfinance で取得できなかった場合、その特徴量だけ `contribution: null` になります (他の特徴量は影響なし)。

#### エラー
- 推論がまだ1度も走っていない (= explanations データなし) → **HTTP 404**

---

### 3.4 `GET /api/metrics/accuracy?days=N` — 予測精度サマリー

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

### 3.5 `GET /api/adr/deviation` — 東証銘柄と ADR の乖離率

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

### 3.6 `GET /api/markets/us` — 米国マーケット (前日終値)

NYダウ / NASDAQ / S&P 500 / USD/JPY の **直近終値・前日比・変化率** を返します。ダッシュボードの「米国マーケット (前日終値)」カードにそのまま使えます。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `no_cache` | 真偽 | 任意 | `false` | `true` で強制再取得 (通常は不要) |

#### キャッシュ仕様
yfinance を内部で 4 回叩くため、初回は **約 2〜5 秒** かかります。レスポンスは **10 分間メモリにキャッシュ**され、2 回目以降は瞬時に返ります。

#### レスポンス例

```json
{
  "fetched_at": "2026-05-05T11:40:52+09:00",
  "cached": false,
  "cache_age_seconds": 0,
  "items": {
    "dow": {
      "name": "NYダウ",
      "symbol": "^DJI",
      "close": 48941.90,
      "change": -557.37,
      "change_pct": -0.0113
    },
    "nasdaq": {
      "name": "NASDAQ",
      "symbol": "^IXIC",
      "close": 25067.80,
      "change": -46.64,
      "change_pct": -0.0019
    },
    "sp500": {
      "name": "S&P 500",
      "symbol": "^GSPC",
      "close": 7200.75,
      "change": -29.37,
      "change_pct": -0.0041
    },
    "usd_jpy": {
      "name": "USD/JPY",
      "symbol": "JPY=X",
      "close": 157.21,
      "change": 0.36,
      "change_pct": 0.0023
    }
  }
}
```

#### フィールドの意味

| フィールド | 説明 |
|---|---|
| `fetched_at` | 取得日時 (JST) |
| `cached` | キャッシュからの応答か (true/false) |
| `cache_age_seconds` | キャッシュ生成からの経過秒数 |
| `items.<キー>.name` | 表示用日本語名 |
| `items.<キー>.symbol` | yfinance のシンボル |
| `items.<キー>.close` | 直近終値 |
| `items.<キー>.change` | 前日比 (絶対値) |
| `items.<キー>.change_pct` | 前日比 (小数。0.01 = 1%) |

`items` のキーは固定 4 種:
- `dow` (NYダウ)
- `nasdaq` (NASDAQ総合)
- `sp500` (S&P 500)
- `usd_jpy` (米ドル/円レート)

取得失敗した銘柄は `close` / `change` / `change_pct` が `null` になります (例: yfinance 一時障害)。

#### JavaScript 使用例

```javascript
const res = await fetch("/api/markets/us");
const data = await res.json();

// 4 枚のカードを描画
Object.entries(data.items).forEach(([key, m]) => {
  const card = document.getElementById(`market-card-${key}`);
  if (m.close === null) {
    card.querySelector(".value").textContent = "—";
    return;
  }
  const isUp = m.change >= 0;
  card.querySelector(".name").textContent  = m.name;
  card.querySelector(".value").textContent = m.close.toLocaleString();
  card.querySelector(".change").innerHTML  = `
    <span class="${isUp ? 'up' : 'down'}">
      ${isUp ? '▲' : '▼'} ${Math.abs(m.change).toFixed(2)}
      (${(m.change_pct * 100).toFixed(2)}%)
    </span>
  `;
});
```

#### 注意点

- **初回呼び出しは約2〜5秒**かかります。フロント側でローディング表示を出してください。同じセッションで2回目以降は瞬時に返ります。
- 表示する数字は **直近の取引日終値**。米国市場が閉まれば翌朝まで値は変わりません。
- 一時的に yfinance が落ちている場合、該当銘柄だけ `null` を返します (502にはしません)。フロント側で `null` チェックしてください。

---

### 3.7 PTS 系エンドポイント (Japannext PTS / Kabutan 集計)

**3 つの PTS 系エンドポイント** で、TSE 通常市場の前後・休憩中に発生する値動きを取得できます。データソースは [Kabutan](https://kabutan.jp/) の PTS ランキングページ (デイ/ナイト/出来高) を 5 分 TTL でキャッシュ。

> 💡 PTS (Proprietary Trading System) = 私設取引システム。Japannext PTS が主要。デイタイム 8:20-16:00、ナイトタイム 16:30-翌6:00。TSE 寄付前の値動きを観測できる。

#### 3.7.1 `GET /api/markets/pts/overnight` — PTS ナイト + TSE 乖離

**用途**: 引け後のニュース反応・板の動きを反映した「翌朝寄付き要注目銘柄 TOP15」を提供。

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `no_cache` | bool | false | true で強制再取得 |

##### レスポンス例

```json
{
  "fetched_at": "2026-05-06T07:00:00+09:00",
  "session": "night",
  "source": "kabutan",
  "cached": false,
  "cache_age_seconds": 0,
  "count": 15,
  "items": [
    {
      "rank": 1,
      "code": "285A",
      "name": "キオクシア",
      "market": "東Ｐ",
      "tse_close": 36410.0,
      "pts_price": 37098.0,
      "change_yen": 688.0,
      "change_pct": 1.89,
      "trading_value_million_jpy": 4622.0,
      "kabutan_url": "https://kabutan.jp/stock/?code=285A"
    }
  ]
}
```

##### フィールド

| フィールド | 説明 |
|---|---|
| `code` | 銘柄コード (4-5 桁) |
| `name` | 銘柄名 (日本語) |
| `market` | 市場区分 (例: 東Ｐ=東証プライム / 東Ｓ=スタンダード / 東Ｇ=グロース / 東Ｅ=ETF) |
| `tse_close` | 直近の TSE 通常取引終値 (円) |
| `pts_price` | PTS 直近約定値 (円) |
| `change_yen` / `change_pct` | TSE 終値からの差 (円 / %) — **PTS で +1.89% 動いたら、TSE 寄付も同方向に動く可能性が高い** |
| `trading_value_million_jpy` | PTS ナイト 累計売買代金 (百万円) |
| `kabutan_url` | 銘柄詳細ページ |

#### 3.7.2 `GET /api/markets/pts/premarket` — PTS デイ + GAP 予想

**用途**: 朝 8:20-9:00 の PTS デイタイム値動きから「TSE 寄付 GAP 予想」を作る。**朝 8:50 頃に呼び出すのが最適**。

レスポンス構造は overnight と同じ (`session: "day"`)。`change_pct` がそのまま GAP 予想値。

#### 3.7.3 `GET /api/markets/pts/volume_surge` — 異常出来高検知

**用途**: PTS ナイト出来高 ÷ TSE 30 日平均出来高 (= **surge_ratio**) で「異常な流動性スパイク」を検出。突発材料・決算サプライズ等の早期察知。

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `no_cache` | bool | false | true で強制再取得 |
| `min_surge_ratio` | float | 0.5 | この値以下の銘柄を除外 |

##### レスポンス例

```json
{
  "fetched_at": "2026-05-06T07:00:00+09:00",
  "session": "night",
  "source": "kabutan + yfinance",
  "min_surge_ratio": 0.5,
  "count": 3,
  "items": [
    {
      "code": "7162",
      "name": "アストマクス",
      "market": "東Ｓ",
      "tse_close": 800.0,
      "pts_price": 1015.0,
      "change_pct": 26.85,
      "pts_volume": 373500,
      "tse_avg_volume_30d": 145503,
      "surge_ratio": 2.57,
      "kabutan_url": "https://kabutan.jp/stock/?code=7162"
    }
  ]
}
```

##### フィールド

| フィールド | 説明 |
|---|---|
| `pts_volume` | PTS ナイト累計出来高 (株数) |
| `tse_avg_volume_30d` | TSE 過去 30 営業日の平均出来高 (yfinance より) |
| `surge_ratio` | `pts_volume / tse_avg_volume_30d`。**> 1.0 で要注意、> 2.0 で確実に何か材料あり** |

##### 注意点

- 初回呼び出しは yfinance に銘柄ごとに問合せるため **5〜15 秒** かかります。30 日分 EOD なので 2 回目以降キャッシュは速い。
- TSE 30 日平均が取れない銘柄 (新規上場・上場廃止間際等) は items から除外されます。

#### JavaScript 使用例 (3 種を組み合わせる)

```javascript
// 1. 翌朝寄付き要注目 (引け後)
const ovrn = await (await fetch("/api/markets/pts/overnight")).json();

// 2. 寄付前 GAP 候補 (朝 8:50)
const pre = await (await fetch("/api/markets/pts/premarket")).json();

// 3. 異常出来高 (突発材料検知、surge >= 2.0 で絞る)
const surge = await (await fetch("/api/markets/pts/volume_surge?min_surge_ratio=2.0")).json();

// 共通の描画関数
const renderRow = (it) => {
  const dir = (it.change_pct ?? 0) >= 0 ? "▲" : "▼";
  const cls = (it.change_pct ?? 0) >= 0 ? "up" : "down";
  return `<tr class="${cls}">
    <td>${it.code}</td><td>${it.name}</td>
    <td>${it.tse_close?.toLocaleString()}</td>
    <td>${it.pts_price?.toLocaleString()}</td>
    <td>${dir} ${Math.abs(it.change_pct ?? 0).toFixed(2)}%</td>
    <td><a href="${it.kabutan_url}" target="_blank">詳細</a></td>
  </tr>`;
};
```

#### 共通の注意点

- **Kabutan の Bot 対策**: 過剰な連続アクセスで一時的に `403` を返すことがあります。本実装は 5 分 TTL キャッシュ + 実ブラウザ風 User-Agent で対策済み。
- **ToS**: 株探の利用規約上、個人/小規模ダッシュボード利用は通例 OK ですが、大量配信や商用は問い合わせ推奨。
- **本番 ECS は NAT Gateway 未設置**のため、本番デプロイ時は外部 HTTPS 経路の準備が必要 (yfinance / Polymarket と同じ既知制約)。

---

### 3.8 `GET /api/markets/polymarket` — Polymarket 予想市場 (センチメント)

予想市場プラットフォーム [Polymarket](https://polymarket.com/) から、日本株デイトレに有用な11マーケットの**現在の確率**をまとめて返します。Fed・日銀の次回金利決定や地政学リスクなど、価格データには現れない**フォワードルッキングなセンチメント指標**として使えます。

> 💡 **自動ローリング設計**: マスタ (`api/data/polymarket_master.json`) の各マーケットはキーワード検索で動的に Polymarket 上の event を見つけます。「FOMC 6月」のような月固定ではなく **「次回 FOMC」** として常に最新会合に追従するので、月をまたいでもマスタの書き換えは原則不要です。

#### クエリパラメータ
| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `no_cache` | 真偽 | 任意 | `false` | `true` で強制再取得 |

#### キャッシュ仕様
Polymarket Gamma API を 8 ページ分 (約 4,000 events) 走査するため初回は **約 7〜15 秒** かかります。レスポンスは **30 分間メモリにキャッシュ**されます。

#### レスポンス例 (一部抜粋)

```json
{
  "fetched_at": "2026-05-05T22:00:00+09:00",
  "cached": false,
  "cache_age_seconds": 0,
  "source": "polymarket-gamma-api",
  "count": 10,
  "items": [
    {
      "rank": 1,
      "slug": "fed-decision-in-june-825",
      "label": "次回 FOMC 据え置き確率",
      "category": "金融政策",
      "category_key": "monetary",
      "main_outcome": {
        "name": "No change",
        "name_jp": "据え置き",
        "probability": 0.955
      },
      "all_outcomes": [
        { "name": "No change",        "probability": 0.955 },
        { "name": "25 bps decrease",  "probability": 0.025 },
        { "name": "25 bps increase",  "probability": 0.009 },
        { "name": "50+ bps decrease", "probability": 0.004 },
        { "name": "50+ bps increase", "probability": 0.004 }
      ],
      "volume_usd": 18077785.0,
      "liquidity_usd": 250000.0,
      "resolution_date": "2026-06-17",
      "polymarket_url": "https://polymarket.com/event/fed-decision-in-june-825",
      "description_jp": "次回 FOMC 会合の政策金利決定。No change = 据え置き確率。月またぎで自動的に次の会合に追従する。",
      "impact_on_n225": "据え置き確率上昇 → ハト派観測弱まる → USD/JPY 上昇 → N225 上昇要因",
      "available": true
    }
    /* ... 残り 9 件 ... */
  ]
}
```

#### フィールド意味

**トップレベル**

| フィールド | 説明 |
|---|---|
| `fetched_at` | 取得日時 (JST) |
| `cached` / `cache_age_seconds` | キャッシュ状態 |
| `source` | 常に `polymarket-gamma-api` |
| `count` | 返却件数 (常に 10 想定) |

**`items[]` 各マーケット**

| フィールド | 説明 |
|---|---|
| `rank` | 重要度ランク (1〜10、フロントの並び順保持に使う) |
| `slug` | Polymarket 上の一意 ID |
| `label` | **日本語表示名** (カードのタイトル) |
| `category` / `category_key` | カテゴリ表示名と英字キー (UI のフィルタ・色分け用) |
| `main_outcome` | **画面に大きく出す確率値** |
| `main_outcome.name` | Polymarket 上の outcome 名 (英語) |
| `main_outcome.name_jp` | 日本語表示名 |
| `main_outcome.probability` | **現在の確率 (0〜1)** — UI では `× 100` で % 表示 |
| `all_outcomes` | 全 outcome の確率 (詳細パネル用) |
| `volume_usd` | 累計取引高 USD (信頼性の目安) |
| `liquidity_usd` | 板の厚み |
| `resolution_date` | 決着日 (YYYY-MM-DD) |
| `polymarket_url` | 「詳細を見る」リンク用 |
| `description_jp` | ツールチップ用 日本語解説 |
| `impact_on_n225` | **「これが動いたら日本株にどう効くか」のヒント** |
| `available` | データ取得成功か |

**カテゴリ一覧**

| `category_key` | `category` (表示名) | 該当マーケット |
|---|---|---|
| `monetary` | 金融政策 | FOMC, Fed利下げ回数, BOJ, RBA |
| `fx` | 為替 | USD/JPY |
| `equity_proxy` | 米株プロキシ | NVIDIA時価総額1位 |
| `geopolitics` | 地政学 | 中台 |
| `us_macro` | 米国経済 | 米国リセッション |
| `japan_macro` | 日本経済 | 日本リセッション |
| `risk_appetite` | リスク選好 | Bitcoin |

#### JavaScript 使用例

```javascript
const res = await fetch("/api/markets/polymarket");
const data = await res.json();

// シンプルカード一覧 (rank 順、絶対値の大きい確率を強調)
data.items.forEach(m => {
  if (!m.available) return;
  const card = document.createElement("div");
  card.className = `polymarket-card category-${m.category_key}`;
  const prob = m.main_outcome.probability;
  const probPct = (prob * 100).toFixed(1);
  card.innerHTML = `
    <div class="cat">${m.category}</div>
    <h3>${m.label}</h3>
    <div class="prob">${probPct}%</div>
    <div class="outcome">${m.main_outcome.name_jp}</div>
    <a href="${m.polymarket_url}" target="_blank" rel="noopener">詳細 →</a>
  `;
  card.title = m.description_jp + "\n\n[N225への影響]\n" + m.impact_on_n225;
  document.getElementById("polymarket-section").appendChild(card);
});
```

#### 注意点

- **初回呼び出しは約 7〜15 秒**かかります (Polymarket Gamma API を 4000 events 走査するため)。フロント側でローディング表示を出してください。同セッション 30 分以内の 2 回目以降は瞬時。
- 一時的に Polymarket から該当 event が見つからない場合 `available: false` で他フィールドが `null` になります。フロント側でケアしてください。
- マスタ (`api/data/polymarket_master.json`) のキーワード検索方式により、月またぎでも次回会合等を自動追従します。**手動更新が必要なのは年単位のマーケット (年内リセッション等) のみ**。

---

### 3.9 `GET /api/getdaytradelist` — デイトレード注目銘柄 (既存)

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
