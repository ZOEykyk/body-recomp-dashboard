# Smart Food Capture & Nutrition Accuracy

## Purpose

Smart Food Captureは、ユーザーがJSON Schemaを意識せず、食品名検索、候補確認、数量、摂取状態、栄養値編集を通して日次記録を作るための入力層である。

## Architecture

```text
Food search / editor
↓
FoodCandidate
↓
Food Resolver and Food Knowledge Snapshot
↓
User confirmation
↓
Captured Food state
↓
Consumed-only Daily Nutrition
↓
Canonical Builder
↓
Schema 1.0 validation, normalization 0 changes
↓
records.csv projection and Food Encounter
```

- `smart_food_capture.py`: Pureな候補、検索順位、数量換算、日次集計、Canonical Builder。
- `smart_food_capture_ui.py`: Streamlitの検索、候補、編集、Purchased/Consumed、Source/Confidence表示。
- `personal_food_master.confirm_capture_food()`: ユーザーが明示確認した値だけを既存Repositoryへ永続化する境界。
- `food_resolver.py`: 食品解決の唯一の経路。PR15専用lookupは追加しない。

## Resolution Priority

1. 今回入力の明示栄養値
2. Personal confirmed Food Master
3. Official source
4. Generic trusted source
5. Estimate / Fallback

Personal Food Masterで選択されたラベル値は`personal_master`として表示する。元のnutrition source metadataは保持するが、画面では「過去の確認値」と明示する。

## Confirmed and Estimated

- `user_label`: 今回ユーザーが商品ラベルで確認。High。
- `personal_master`: 過去の確認値を再利用。High。
- `official`: 公式商品・栄養情報。High。
- `trusted_catalog`: 信頼済み汎用カタログ。Medium。
- `estimated`: ユーザーが概算として入力、またはfallbackを採用。Low。
- `unknown`: 栄養値未確認。Low。

「この食品の栄養値を今後も使用する」は`user_label`を選択した場合だけ有効である。EstimatedとUnknownはactive Personal Foodへ昇格しない。再確認で値が変わった場合、以前のexplicit sourceは`superseded`として残し、新しい確認値を選択する。

## Purchased and Consumed

Captured Foodは購入・用意した`quantity`と、実際に食べた`consumed_quantity`を分ける。

- `consumed_quantity = 0`: Planned。Daily nutrition、Body Score、Canonical meals、Food Encounterへ入らない。
- `0 < consumed_quantity < quantity`: Partially consumed。食べた数量だけを換算する。
- `consumed_quantity = quantity`: Consumed。全量を換算する。

Planned状態は現在のStreamlit session内の入力状態であり、日次保存対象ではない。Consumedへ変更して日次保存した時点で既存Encounter経路へ入る。

## Unknown Policy

Unknown Foodは0 kcalへ変換しない。日次表示は既知カロリーとUnknown件数を分ける。ユーザーが概算を入力した場合だけ`estimated`として集計し、確定値とは異なる表示にする。

## Canonical Builder

`canonical_builder_result(daily, items)`はPure Functionであり、入力を書き換えない。Consumed FoodだけからSchema 1.0を生成し、PR14 Schema Contract Validatorを通す。UI生成JSONはCompatibility normalization 0件でなければ保存できない。

Canonical Schema 1.0は変更していない。Source、Confidence、Purchased状態は入力・Food Knowledge層の責務であり、日次CanonicalへはConsumed itemの名前、数量、nutrition、説明用notesだけを投影する。

## Data Migration Decision

PR15ではDB migrationを追加しない。

- Confirmed Foodは既存`foods`、`food_aliases`、`nutrition_sources`、`nutrition_facts`で表現できる。
- Consumed Food Encounterは既存`food_encounters`契約を利用できる。
- Plannedは日次栄養でも履歴Encounterでもないため、現在はsession stateに置く。
- `records.csv`、Canonical Schema 1.0、Supabase RLS、owner isolationは変更しない。

Planned inventoryを再起動後も保持する要件が生じた場合は、Food Encounterへ流用せず、将来の独立inventory/capture contractとして設計する。

## PR16 OCR Handoff

PR16 Smart Label Capture / OCRは次の順で接続する。

```text
Nutrition label image
↓
OCR adapter
↓
FoodCandidate
↓
Existing editor and user confirmation
↓
Personal Food Master
```

候補は少なくともname、calories、protein、fat、carbs、quantity、unit、source、confidence、raw_text、confirmedを持てる。OCR固有の画像処理、モデル名、raw responseはResolverへ混ぜない。

PR16候補範囲:

- 栄養ラベル画像アップロード
- OCRと商品名・Calories・P/F/C抽出
- 候補Previewと手動修正
- 明示確認後のFood Master登録
- 将来のバーコード・商品画像adapter

本格OCR、Vision API、バーコード、画像保存はPR15の対象外である。
