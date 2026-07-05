# 手間いらず ターゲットプライス（TP）設定 自動生成ツール

「手間いらず 自動」に読み込ませるターゲットプライス設定用Excelファイル（DATAシート）を自動生成するツール。

TP設定は、残室数とリードタイム（予約日から宿泊日までの日数）に基づいて自動適用される料金ランクを決定するマトリクス。本ツールは1つのベースマトリクスから**上り幅（差分）を維持**するルールで全料金ランク分（通常100個程度）のマトリクスを生成する。

## セットアップ

```bash
cd tp_generator
pip install -r requirements.txt
```

## 使い方

### 1. 既存の元ファイルから設定を抽出する

```bash
python generate_tp.py import --xlsx 元ファイル.xlsx --out config/施設名.yaml
```

DATAシートの全マトリクスを読み取り、残室軸×リードタイム軸の組み合わせでルールタイプを自動特定して設定YAMLを出力する。抽出された適用範囲・ベースは必ず施設の運用方針と照合すること。

### 2. 設定YAMLからTP設定Excelを生成する

```bash
python generate_tp.py generate --config config/sample_facility.yaml --out output.xlsx
```

生成後、検証チェックリスト（マトリクス総数・配列構造・2行空け・打ち止め・料金ランク順など）が自動実行される。

### 3. 生成済みファイルの検証のみ実行する

```bash
python generate_tp.py validate --xlsx output.xlsx
```

## 設定YAMLの形式

```yaml
room_type: 女性ドミトリー
excluded_room_type: ""
# master: を省略すると典型的な料金ランク一覧（100個）が使われる
rules:
  - name: 平日/週末用
    base_rank: (平日) 4000        # ベースマトリクスの料金ランク
    apply_from: (平日) 2500       # 適用範囲の下限
    apply_to: (週末) 7900         # 適用範囲の上限
    lead_times: [0, 14, 16, ..., 365]   # リードタイム軸
    stock_axis: [35, 30, 25, ..., 3]    # 残室軸
    matrix:                       # ベースマトリクス（行=リードタイム、列=残室）
      - ["(平日) 3500", "(平日) 3500", ...]
      - ...
```

サンプル設定は `scripts/make_sample_config.py` で再生成できる（ダミーデータ）。

## 計算ルール（仕様書準拠）

- **上り幅維持**: `新しい料金 = 新しいベース料金 + (元の料金 - 元のベース料金)`
  - 単純な+100円加算ではない
- **上下限打ち止め**: MASTERの最低/最高料金ランクで打ち止め
- **切り上げ**: MASTERに存在しない金額は最も近い上位ランクに切り上げ
- **カテゴリ遷移**: (平日)→(週末)→(特別) は金額帯から自動決定

## 出力Excelの構成

| シート | 役割 |
|---|---|
| はじめに | 説明・注意事項 |
| MASTER | 料金ランク一覧の定義 |
| SETTING | 各種設定（現状はプレースホルダ） |
| DATA | TPマトリクス本体（マトリクス間2行空け、厳守配列構造） |

**注意**: MASTER/SETTINGシートの実際のセル配置は仕様書に明記がないため、実際の元ファイルと差異があれば `tp/excel_writer.py` を調整すること。DATAシートの配列構造は仕様書3章に完全準拠している。

## テスト

```bash
python -m pytest tests/
```

仕様書の計算例（上り幅プラス13500円 / 下限打ち止め / カテゴリ遷移8400円）、打ち止めルール、生成→出力→読み戻しのラウンドトリップを検証している。

## ディレクトリ構成

```
tp_generator/
├── generate_tp.py        # CLI（generate / import / validate）
├── tp/
│   ├── master.py         # 料金ランク（MASTER）の定義・切り上げ・打ち止め
│   ├── engine.py         # 上り幅ルールによるマトリクス生成エンジン
│   ├── excel_writer.py   # 厳守配列構造でのExcel出力
│   ├── importer.py       # 元ファイルのDATAシート解析
│   └── validator.py      # 検証チェックリスト
├── config/
│   └── sample_facility.yaml  # サンプル施設設定（ダミー）
├── scripts/
│   └── make_sample_config.py
└── tests/
```
