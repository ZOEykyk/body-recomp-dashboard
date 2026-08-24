# body-recomp-dashboard

ボディリコンプ管理システム。食事、体重、歩数、睡眠、筋トレ、体調を記録し、減量と筋力維持の進捗を可視化します。

Project BodyOS は、日々の行動を同じ物差しで眺めつつ、通常日・イベント日・体調回復日を無理に同じ基準で評価しないための記録システムです。長期的には 75〜76kg を目標体重帯とし、体重だけでなく食事、タンパク質、歩数、筋トレ、睡眠、体調を含めてコンディションを管理します。

## Project Documentation

- [Product Vision](docs/PRODUCT_VISION.md)
- [BodyOS Constitution](docs/BODYOS_CONSTITUTION.md)
- [Development Standard](docs/DEVELOPMENT_STANDARD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data Standard](docs/DATA_STANDARD.md)
- [Roadmap](docs/ROADMAP.md)
- [Food Knowledge Foundation](docs/FOOD_KNOWLEDGE.md)
- [Smart Food Capture](docs/SMART_FOOD_CAPTURE.md)
- [Food Knowledge Supabase Operations](docs/SUPABASE_FOOD_KNOWLEDGE.md)
- [Food Knowledge Production Runbook](docs/FOOD_KNOWLEDGE_RUNBOOK.md)
- [PR12 Acceptance Test](docs/PR12_ACCEPTANCE_TEST.md)
- [PR12 Deployment Checklist](docs/PR12_DEPLOYMENT_CHECKLIST.md)
- [PR12 Migration Review](docs/PR12_MIGRATION_REVIEW.md)
- [BodyOS Import Schema 1.0](docs/bodyos-import-schema.md)
- [BodyOS JSON Authoring Guide](docs/bodyos-json-authoring-guide.md)
- [PR13 Acceptance Test](docs/PR13_ACCEPTANCE_TEST.md)
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

食事テキストはまず `food_parser.py` で構造化され、すべて `food_resolver.py` の `resolve_food_text()` へ渡されます。Resolverは明示栄養、Personal Food Master、公式カタログ、汎用カタログ、fallbackの候補を収集してから、`food_source_policy.py` の共通優先順位で最終決定します。手入力、JSON Import、カロリー推定、Encounter保存、Nutrition Intelligenceで順序は変わりません。

`food_lookup_catalog.json` は公式商品ページまたは公式栄養表を出典として持つ小規模なlookupカタログです。食品名・ブランド・variant・sizeが一意に照合できるときだけ利用します。照合できない場合は、既存の `food_dictionary.json`、`brand_dictionary.json`、`restaurant_dictionary.json` の辞書とfallbackを使います。食品を追加したい場合は、アプリ本体へ条件分岐を増やさず、対応するJSONカタログへ追加してください。

新規保存・新規JSON import時には、`Personal Food Master` が食品遭遇をローカルに記録します。未知食品や明示ラベルはまずreviewable candidateとして保存され、推定値だけを信頼済み食品へ自動昇格しません。公式の確認済みsourceを持つ食品、または明示的にreviewされたcandidateだけが再利用可能なactive foodになります。Personal Food Masterは`records.csv`とは分離され、既存の履歴を自動変換しません。

Personal Food MasterとFood EncounterはRepository設定によりSupabaseへ永続化できます。未設定時は従来どおり`personal_food_master.json`と`food_encounters.jsonl`を使うlocal MVPで、Streamlit Cloud上のdurabilityは保証されません。Supabase SQL、Secrets、移行、障害時fallback、rollbackは[運用手順](docs/SUPABASE_FOOD_KNOWLEDGE.md)を参照してください。`records.csv`のGitHub保存とは独立しています。

画面下部の`Food Knowledge`では登録食品、Personal、Official、Fallback、Confidence、利用回数、最近の更新に加え、Storage、Connection、Repository、最終read/write、migration、未同期件数を確認できます。続く`Personal Food Master`ではactive foodとpending candidateを管理できます。JSON Import完了時には解決元とEncounter saved、Duplicate skipped、Save failedを表示します。

`Nutrition Intelligence` は共有Food Resolverと読み取り専用Knowledge Snapshotを利用するpure functionです。Personal Foodの確認済み栄養も、手入力やImportと同じSource Policyで評価されます。Body Scoreは変更せず、Nutrition Score、記録状況、信頼度、良い点、改善優先項目、次の最大3アクションを表示します。

v1の標準目標は、カロリー2,200kcal、タンパク質は体重があれば1.6g/kg（不明時120g）、脂質25-35%エネルギー、炭水化物35-55%、食物繊維21g、食塩相当量7.5g以下、野菜3品相当です。これは安全な既定値であり、個人の医療・栄養指示を推定するものではありません。栄養値の出典とPFCのカバー率から信頼度を出し、未確認食品やfallbackが多い日は参考値として控えめに表示します。将来のLLMはこの構造化結果の言い換えにだけ使い、ルールと保存値を置き換えません。

食事テキストに `289 kcal` のような明示的なkcal値が含まれる場合は、その値を最優先します。複数のkcal値がある場合は合計します。これは食べた特定パッケージのラベル値として扱われ、公式値や推定値で黙って置き換えません。異なるsourceの栄養値が競合する場合は、優先sourceを示したうえでreview対象として残します。

`ゆで卵2個`、`ジョンソンヴィル2本`、`おにぎり2個` のような数量は、辞書の1個あたり推定値に個数を掛けて計算します。括弧や中黒で区切られた `ベーグル（卵1個・有塩バター7g）` のような複合入力も、食品ごとに分解して推定します。

辞書で一部しか検出できない場合は、残りを0kcalにはせず、食事種別ごとの控えめなフォールバックを足します。推定の確からしさは `カロリー推定信頼度` に `high`、`medium`、`low` で保存されます。

正確さが重要な日は、各食事のカロリー手入力欄、またはChatGPTログ内の明示的なカロリー値を使ってください。

## Smart Food Capture

「今日の記録」では食品名からPersonal Food Master、利用頻度、最近の食品、Official、Genericの順で候補を確認できます。数量、単位、Calories、P/F/C、食事区分、摂取数量、備考を編集でき、SourceとConfidenceを確定・推定・不明で区別します。

商品ラベルを確認した値は「この食品の栄養値を今後も使用する」を明示した場合だけPersonal Food Masterへ保存されます。次回は過去の確認値が推定より先に再利用されます。概算値と不明値は確定Foodへ自動昇格しません。

購入・予定の食品は摂取数量が0の間、Daily calories、Nutrition Intelligence、Body Score、Canonical JSON、Food Encounterへ入りません。一部を食べた場合は摂取数量だけを換算します。不明食品は0 kcalではなく「不明」として件数を表示します。

Daily Inputから生成したCanonical Schema 1.0は保存前にPR14 Validatorを直接通り、Compatibility normalization 0件の場合だけ保存できます。JSON ImportとCanonical PreviewはAdvanced用途として引き続き利用できます。

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

### Runtime Performance

Repository/Supabase client、静的Food Catalog、ユーザー別Food Knowledge、CSV読込、Dashboardの決定的な集計は、それぞれの更新頻度に合わせてキャッシュします。Personal Foodは短いTTLと書き込みrevisionで管理され、保存・Alias追加・栄養値更新後は次のrerunで即時反映されます。

開発時に`BODYOS_PERFORMANCE_DEBUG=1`を設定すると、画面末尾の`Performance Debug`で主要処理の直近値・中央値・最大値を確認できます。計測には処理名と時間だけを保存し、食品内容、ユーザー情報、Secretsは記録しません。計測条件とBefore/Afterは[PR15.1 Performance Report](docs/validation/pr15_1/PERFORMANCE.md)を参照してください。

Dashboard v1.0は、開いた直後に今日の状態を把握できるように、Body Score、今日のメトリクス、Workout Intelligence Top 3、コア推移、履歴、詳細分析の順に表示します。主要チャートは Body Score、体重、摂取カロリー、歩数に絞り、低価値な補助チャートは主画面から外しています。この整理は表示のみの変更で、履歴データ、CSVスキーマ、JSON取り込み、採点ルールは変更しません。

## Data Integrity

体重の欠損値（空欄、null、NaN、0、`"0"`、数値として読めない値）は、週平均・月平均・7日平均・体重推移・到達予測では有効な体重として扱いません。欠損体重はダッシュボード上で `—` と表示し、体重チャートに 0kg の点は描画しません。

食事欄の `なし`、`食べていない`、`未食`、`抜き`、`スキップ`、`朝食なし`、`昼食なし`、`夕食なし`、`晩御飯なし`、`晩ご飯なし` などは、明示的な食事なしとして 0 kcal にします。未知の非空テキストは従来どおり fallback 推定の対象です。

既存の履歴レコードは通常起動だけでは自動書き換えしません。新しいルールは新規作成、明示的な編集、または明示的な再インポート時に適用します。

## BodyOS JSON Import

アプリの`BodyOS JSON Import`では、正式Schema 1.0または従来のBodyOS/ChatGPT JSONを受け付けます。保存前に対象日、食事件数、Workoutのセッション・種目・セット数、既存日との競合、警告をPreviewできます。

PR14では`schemas/bodyos-daily-log.schema.json`を唯一の正として、Compatibility変換後に全SchemaエラーをPath付きで検証します。意味が明確で情報損失や競合のないaliasだけを変換し、変更内容をNormalization Reportへ表示します。Previewでは保存されるCanonical JSONを確認でき、そのJSONは再Import時に追加変換0件で通過します。enum外basis、競合alias、複数Workout session、未知fieldは推測せず拒否します。

同一日がある場合は、初期値`更新`のほか、`置換`または`中止`を明示的に選択できます。同一JSONを再実行しても日次行、Workout、Food Encounterは重複しません。内容を変更した同日JSONは同じ日次行を更新し、Food Encounterには新しいcontent fingerprintが使われます。

保存後は項目別Diagnosticsとカロリー不明件数を表示します。明示栄養を最優先し、なければPersonal、Official、Genericの順で一度だけ解決します。Fallback値は既存手入力の概算では維持しますが、正式Importでは既知栄養へ昇格せず`null`と不明件数を保存します。

正式な項目、Workoutセット形式、欠損値、互換ルールは[BodyOS Import Schema 1.0](docs/bodyos-import-schema.md)、コピー用の見本とNG/OKは[BodyOS JSON Authoring Guide](docs/bodyos-json-authoring-guide.md)を参照してください。保存済み日は同じSchemaでJSON Exportできます。

週ごとの筋トレ回数は、保存値の文字列完全一致ではなく、正規化後の筋トレ有無で集計されます。

## Workout Intelligence

Workout Intelligence v1 は `workout_intelligence.py` の `analyze_workout(record, history=None)` で筋トレ自由記述を解析します。

対応する内容:

- 種目名の抽出
- `90kg 5,6,6,4` や `90kg×5×4` などの重量・回数・セット解析
- 推定ボリュームと推定1RM
- 履歴がある場合の簡易PR候補
- 次回ターゲットの提案

解析は概算です。既存の`筋トレ内容`テキストはそのまま読めます。正式Importはセッション、種目、順序付きセットを`構造化筋トレJSON`へ保存し、既存表示用テキストも同時に保持します。

日付や数値が読み取れない場合は、アプリ上に「何件目のどの項目が読み取れなかったか」を表示します。
