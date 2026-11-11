# RheoSuperposition Architecture

## 基本方針

GUIイベント、アプリの処理手順、数値計算、ファイル入出力、描画を分離しています。
数値計算モジュールはTkinterへ依存せず、単体テストできる構成です。

## モジュール

### `models.py`

- `TTSConfig`
- `AppState`
- アプリ全体で共有する設定と状態の型

### `readers.py`

- stacked-header形式の読込
- column-names形式の読込
- delimiter処理
- linear/log10/ln変換
- 温度ラベルとIGOR trace情報の解析

### `losses.py`

- 自作複合損失
- pointwise lossと平均lossを分離

### `shifts.py`

- スプライン生成
- aT推定
- bT推定
- overlap判定
- shifted dataframe生成

このモジュールはファイル保存やGUI描画を行いません。

### `exporters.py`

- shift factor CSV
- shifted data CSV
- IGOR command

### `plotting.py`

- 温度色
- 未シフト入力プレビュー

既存GUIの高速なArtist更新処理は `gui/app.py` に残しています。今後描画仕様を大きく変更する場合は、horizontal/vertical plot modelとして追加分離できます。

### `settings.py`

- input/outputパスのJSON保存・復元
- ファイルダイアログ初期フォルダの解決

### `controller.py`

- Load → horizontal shift → vertical shift → Export
- Tkinterへ依存しないアプリケーション処理の入口

### `gui/app.py`

- Tkinter画面
- GUI入力値の検証
- controller呼出し
- 手動調整と表示更新

### `gui/widgets.py`

- 編集可能なshift table

## 損失関数

```text
rho(x) = b x^4 / ((0.481 c)^2 + |x|^3)
         + x^2 / ((0.333 c)^2 + x^2)
```

- 第1項：大きな残差ではおおよそ `b |x|` となり、`b` が大きな差への重みを決める
- 第2項：小さな残差では二乗的に増え、大きな残差では1へ近づく
- `c`：大きい残差とみなすおおよその目安
- 既定値：`b=0.1`、`c=0.5`

## v5.0.0 拡張

- `TTSConfig.measurement`：dynamic / relaxation / creep。
- `condition_name` / `condition_unit`：基準条件軸のメタデータ。
- `scalar.py`：時間領域の2列読込、水平・垂直シフトの同時／固定推定、識別困難の診断、シフト済みデータ生成。
- `shifts.py`：dynamicは従来の推定処理を維持し、時間領域はscalar.pyに振り分けます。
- `exporters.py`：内部のaT/bT列を公開出力のa_x/b_yへ変換し、変換式と解析条件を保存します。
- `gui/app.py`：測定形式の切替、条件設定、入力変更時の再読込要求、時間領域の単一応答グラフ。
- `tests/test_time_domain.py`：既知シフト、固定モード、スケール、入力検証、出力、識別困難を確認します。

内部のaT/bTは描画軸・応答への直接倍率です。時間領域では伝統的なa_T（t_reduced = t/a_T）の逆数に当たるため、ユーザー向け名称はa_xに統一します。
