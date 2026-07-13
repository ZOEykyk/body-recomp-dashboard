# body-recomp-dashboard

ボディリコンプ管理システム。食事、体重、歩数、睡眠、筋トレ、体調を記録し、減量と筋力維持の進捗を可視化します。

Project BodyOS は、日々の行動を同じ物差しで眺めつつ、通常日・イベント日・体調回復日を無理に同じ基準で評価しないための記録システムです。長期的には 75〜76kg を目標体重帯とし、体重だけでなく食事、タンパク質、歩数、筋トレ、睡眠、体調を含めてコンディションを管理します。

## Project Documentation

- [BodyOS Constitution](docs/BODYOS_CONSTITUTION.md)
- [Development Standard](docs/DEVELOPMENT_STANDARD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data Standard](docs/DATA_STANDARD.md)
- [Roadmap](docs/ROADMAP.md)
- [Contributing](docs/CONTRIBUTING.md)
- [PRD Template](docs/PRD/PRD_TEMPLATE.md)
- [ADR Template](docs/ADR/ADR_TEMPLATE.md)

## Streamlit Cloudでrecords.csvを永続化する

Streamlit Cloudのファイルシステムは永続化されないため、`records.csv` はGitHub Contents APIでリポジトリ上に保存します。

Streamlit CloudのSecretsに以下を設定してください。

```toml
GITHUB_TOKEN = "GitHub fine-grained personal access token"
GITHUB_REPOSITORY = "ZOEykyk/body-recomp-dashboard"
RECORDS_CSV_BRANCH = "main"
RECORDS_CSV_PATH = "records.csv"
```

`GITHUB_TOKEN` には対象リポジトリのContents read/write権限を付けてください。Secretsが未設定の場合は、ローカルの `records.csv` に保存します。

## 歩数ランク

- S: 12,000歩以上
- A: 10,000歩以上
- B: 8,000歩以上
- C: 6,000歩以上
- D: 6,000歩未満

## カロリー推定

カロリーは概算です。BodyOSはMyFitnessPalのような精密な栄養記録アプリではなく、日々の記録で「明らかにおかしい」と感じない現実的な目安を出すことを目的にしています。

推定は `food_dictionary.json`、`brand_dictionary.json`、`restaurant_dictionary.json` の辞書を使います。食品を追加したい場合は、アプリ本体へ条件分岐を増やさず、JSON辞書へ `name`、`kcal`、`aliases` を追加してください。

食事テキストに `289 kcal` のような明示的なkcal値が含まれる場合は、その値を最優先します。複数のkcal値がある場合は合計します。

`ゆで卵2個`、`ジョンソンヴィル2本`、`おにぎり2個` のような数量は、辞書の1個あたり推定値に個数を掛けて計算します。括弧や中黒で区切られた `ベーグル（卵1個・有塩バター7g）` のような複合入力も、食品ごとに分解して推定します。

辞書で一部しか検出できない場合は、残りを0kcalにはせず、食事種別ごとの控えめなフォールバックを足します。推定の確からしさは `カロリー推定信頼度` に `high`、`medium`、`low` で保存されます。

正確さが重要な日は、各食事のカロリー手入力欄、またはChatGPTログ内の明示的なカロリー値を使ってください。

## Mode

毎日の記録には `モード` と `イベント名` を保存できます。

- `NORMAL`: 通常日。食事、歩数、筋トレ、睡眠を通常基準で評価します。
- `EVENT`: 焼肉、飲み会、旅行、デートなど。食事の減点を少し緩め、イベントを楽しみつつ暴食を避けられたかを評価します。
- `RECOVERY`: 体調不良、二日酔い、睡眠不足など。体重減少や筋トレよりも睡眠、体調回復、無理をしない判断を重視します。
- `BULK`: 将来の増量期用。現時点では保存と簡易採点に対応しています。

ChatGPT JSONログでは `mode`, `モード`, `event`, `event_name`, `イベント名` を受け付けます。

## Body Score

Body Score は 100点満点の総合スコアです。ChatGPT JSONログでは Body Score や各内訳スコアを省略してかまいません。アプリ側が最新ロジックで自動計算します。

Body Score は `bodyos_standard.py` の BodyOS Standard v1.0 で計算されます。アプリ、将来のAPI、AI Coach機能は `calculate_bodyos_score(record)` を共通インターフェースとして利用します。

JSONに `body_score` / `Body Score` が含まれている場合、その値は `手動Body Score` として保存し、アプリが計算した `Body Score` と区別します。ダッシュボードや再計算では、最新ロジックによる自動計算スコアを使います。

通常モードの配点目安:

- 体重スコア: 15点
- 食事スコア: 20点
- タンパク質スコア: 15点
- 歩数スコア: 10点
- 筋トレスコア: 10点
- 睡眠スコア: 10点
- 体調スコア: 10点
- 飲酒スコア: 10点

飲酒スコアは `飲酒`, `飲酒内容`, `飲酒レベル` から推定します。飲酒なしは減点なし、軽い飲酒は小さく減点、通常飲酒は中程度減点、濃いハイボール7杯など翌日に影響が出る飲酒は大きく減点します。飲酒内容を具体的に記録すると、Body Scoreの精度が上がります。

ダッシュボードの「Body Scoreを再計算」ボタンを押すと、既存の `records.csv` 全レコードについて最新ロジックで `Body Score` と内訳スコアを再評価し、通常の保存先に反映します。GitHub保存を設定している場合は、GitHub上の `records.csv` も更新されます。

Body Scoreの表示ラベル:

- 90〜100: 🟢 Excellent
- 80〜89: 🔵 Good
- 70〜79: 🟡 Fair
- 60〜69: 🟠 Needs Attention
- 59以下: 🔴 Recovery Needed

ChatGPT JSONログでは `body_score`, `Body Score`, `total_score`, `体重スコア`, `食事スコア`, `タンパク質スコア`, `歩数スコア`, `筋トレスコア`, `睡眠スコア`, `体調スコア`, `飲酒スコア` も受け付けますが、省略推奨です。

## Dashboard Layer

Streamlitアプリの高レベルな流れは `app.py` が担当し、ダッシュボードの描画は `dashboard.py` に分離しています。

- `app.py`: ページ設定、データ読み込み、CSV保存、GitHub保存、手入力フォーム、ChatGPT JSON取り込み
- `dashboard.py`: Dashboard v1.0の情報階層、メトリクス、コア推移チャート、Workout Intelligence表示、直近詳細、履歴テーブル
- `bodyos_standard.py`: `calculate_bodyos_score(record)` による評価
- `workout_intelligence.py`: `analyze_workout(record, history=None)` による筋トレ解析

この分離は保守性のためのリファクタリングで、CSVスキーマ、JSON取り込み、Body Score計算、カロリー推定、Workout Intelligenceの公開インターフェースは変更しません。

Dashboard v1.0は、開いた直後に今日の状態を把握できるように、Body Score、今日のメトリクス、Workout Intelligence Top 3、コア推移、履歴、詳細分析の順に表示します。主要チャートは Body Score、体重、摂取カロリー、歩数に絞り、低価値な補助チャートは主画面から外しています。この整理は表示のみの変更で、履歴データ、CSVスキーマ、JSON取り込み、採点ルールは変更しません。

## Data Integrity

体重の欠損値（空欄、null、NaN、0、`"0"`、数値として読めない値）は、週平均・月平均・7日平均・体重推移・到達予測では有効な体重として扱いません。欠損体重はダッシュボード上で `—` と表示し、体重チャートに 0kg の点は描画しません。

食事欄の `なし`、`食べていない`、`未食`、`抜き`、`スキップ`、`朝食なし`、`昼食なし`、`夕食なし`、`晩御飯なし`、`晩ご飯なし` などは、明示的な食事なしとして 0 kcal にします。未知の非空テキストは従来どおり fallback 推定の対象です。

既存の履歴レコードは通常起動だけでは自動書き換えしません。新しいルールは新規作成、明示的な編集、または明示的な再インポート時に適用します。

## ChatGPT JSONログ形式

アプリの「ChatGPTログ貼り付け」欄には、1日分のJSONオブジェクト、または複数日分のJSON配列を貼り付けます。同じ日付の記録が既にある場合は上書きし、なければ追加します。

```json
{
  "日付": "2026-06-28",
  "mode": "EVENT",
  "event_name": "焼肉",
  "体重": 85.2,
  "歩数": 8200,
  "歩数ランク": "B",
  "睡眠時間": 7.5,
  "朝": "プロテイン、トマトジュース",
  "昼": "うどん、とり天",
  "夜": "鶏むね肉、白米、サラダ",
  "間食": "オイコス",
  "仕事中のドリンク": "コーヒー、カフェラテ",
  "推定摂取カロリー": 1850,
  "筋トレ有無": true,
  "筋トレ内容": "ベンチプレス 90kg 5,6,6,4 / サイドレイズ 12kg 15回",
  "体調": "良い",
  "飲酒": "なし",
  "飲酒内容": "",
  "飲酒レベル": "なし",
  "今日の採点": 85,
  "コメント": "歩数と食事は良好。明日は睡眠を増やす。"
}
```

複数日分の場合:

```json
[
  {
    "日付": "2026-06-28",
    "モード": "NORMAL",
    "体重": 85.2,
    "歩数": 8200,
    "睡眠時間": 7.5,
    "朝": "プロテイン",
    "昼": "うどん",
    "夜": "鶏むね肉",
    "間食": "オイコス",
    "仕事中のドリンク": "コーヒー",
    "推定摂取カロリー": 1850,
    "筋トレ有無": true,
    "筋トレ内容": "ベンチプレス 90kg 5,6,6,4",
    "体調": "良い",
    "飲酒": "なし",
    "今日の採点": 85,
    "コメント": "よくできた"
  }
]
```

英語キーも一部受け付けます。例: `date`, `mode`, `event`, `event_name`, `weight`, `steps`, `sleep_hours`, `breakfast`, `lunch`, `dinner`, `meal`, `snacks`, `work_drinks`, `calories`, `trained`, `workout`, `workout_detail`, `condition`, `alcohol`, `drinking`, `drank_alcohol`, `alcohol_detail`, `alcohol_level`, `drinking_level`, `score`, `body_score`, `total_score`, `comment`。

筋トレ実績は `workout.performed`、`筋トレ有無`、`trained` のいずれでも取り込めます。`あり`、`true`、`yes`、`done`、`実施`、`した` は筋トレあり、`なし`、`false`、`no`、`none`、`休み`、`してない` は筋トレなしとして正規化されます。

`workout.menu` は文字列、配列、オブジェクト配列に対応しています。配列は ` / ` 区切りで保存し、`{"exercise":"ベンチプレス","result":"90kg×5×4"}` のようなオブジェクトは `ベンチプレス 90kg×5×4` の形式に変換して `筋トレ内容` に保存します。

週ごとの筋トレ回数は、保存値の文字列完全一致ではなく、正規化後の筋トレ有無で集計されます。

## Workout Intelligence

Workout Intelligence v1 は `workout_intelligence.py` の `analyze_workout(record, history=None)` で筋トレ自由記述を解析します。

対応する内容:

- 種目名の抽出
- `90kg 5,6,6,4` や `90kg×5×4` などの重量・回数・セット解析
- 推定ボリュームと推定1RM
- 履歴がある場合の簡易PR候補
- 次回ターゲットの提案

解析は概算です。既存の `筋トレ内容` テキストはそのまま保存し、CSVスキーマは変更しません。

日付や数値が読み取れない場合は、アプリ上に「何件目のどの項目が読み取れなかったか」を表示します。
