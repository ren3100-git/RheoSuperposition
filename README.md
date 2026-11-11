# RheoSuperposition v5.0.5

## macOS版のダウンロード

[GitHub Releases](https://github.com/ren3100-git/RheoSuperposition/releases/latest)からZIPをダウンロードして展開してください。配布アプリはApple Silicon（arm64）用です。Intel Macでの動作は確認していません。別端末での起動、Appleによる公証は未確認です。

ソースコードから実行する場合は、以下の環境構築手順に従ってください。


動的粘弾性、応力緩和、クリープの曲線を、指定した基準条件に重ね合わせるmacOSアプリです。

## 測定形式

画面上部の Measurement で選択します。

| 選択値 | 測定 | 1条件あたりの列 |
|---|---|---|
| dynamic | 動的粘弾性 | w, G1, G2 |
| relaxation | 応力緩和 | t, G |
| creep | クリープ | t, J |

入力表の行見出しはCond（条件）、val（変数名）、name（データ名／IGORトレース名）、0、1、2、…です。nameの次の行から数値を入力します。各条件で同じ列構成を繰り返します。時間は正値が必要です。t = 0、ゼロ以下の応答値は使用できません。条件ブロック内の値が1つでも欠損している行は、その条件のデータ対（dynamicでは3列）をまとめて解析から除外します。他の条件の同じ行は保持します。空欄・NaNは欠損値として扱います。各条件に4点以上の異なる横軸値が必要です。

形式を変えても入力表は消去されません。New templateで空のテンプレートへ変更し、データを貼り付けます。Add condition / Delete conditionは測定形式に応じた2列または3列を操作します。

入力スケールは従来通り初期値log10です。Settingsでlinear / log10 / lnを指定します。この設定は横軸・応答値の両方に適用されます。`examples/` のサンプルはlinearです。

## 基準条件

SettingsのConditionで名前と単位を設定します。例：Temperature / °C、Concentration / %、Pressure / MPa。表の条件欄には数値または文字ラベルを入力し、Reference conditionには基準の値またはラベルを指定します。

温度以外の文字ラベルはそのまま保持します。数値条件は基準に近い順、文字条件は表の順番で解析します。単位は設定欄で管理し、温度以外の数値条件には単位を付けずに入力してください。複数の条件軸を同時に推定する機能はありません。

Settingsはウィンドウのサイズを変更でき、項目を縦スクロールできます。Apply／Cancelは下部に固定しています。

シフト係数グラフの横軸にはSettingsのCondition → NameとUnitを表示します（例：Concentration (%)）。Name／UnitはSettingsのApplyで表示に反映します。Settings → Display → Condition axis scaleでlinear / logを選べます。logは全条件が正の数値の場合に使用でき、表示設定だけで切り替わるため再計算は不要です。ゼロ・負値・文字ラベルを含む場合はlinearを使用してください。

Settings → Display → Factor y directionでnormal / invertedを選べます。invertedでは両方のシフト係数グラフの縦軸を反転し、大きい係数を下に表示します。係数の数値やCSV出力は変わりません。再計算は不要で、PNG出力にも表示設定を反映します。

## シフトの定義

```text
x_shifted = x × a_x
response_shifted = response × b_y
Δx = log10(a_x)
Δy = log10(b_y)
```

xはdynamicでは角周波数、relaxation / creepでは時間です。基準条件は常にa_x = b_y = 1です。

a_xは描画軸に対する直接の倍率です。時間についてt_reduced = t / a_Tと定義する場合、a_x = 1 / a_Tです。b_yは測定された応答の直接の倍率で、弾性率とコンプライアンス間の逆数変換は自動適用しません。変換式と条件設定は出力ファイルに保存します。

## 推定と手動調整

Apply data後、Run vertical shiftを直接実行できます。水平推定が未実行の場合はa_x = 1に固定して垂直シフトを推定し、Shift modeをvertical_onlyに設定します。既存の水平シフトがある場合はその値を使用します。

- dynamic：従来のtan δによる水平推定、G′・G″による垂直推定を維持します。
- relaxation / creep：初期設定はhorizontal_onlyです。G(t)またはJ(t)を直接比較して水平移動を求め、垂直倍率は固定します。
- both：時間領域では水平・垂直移動を同時推定します。水平シフトタブの計算ボタンで両者を推定し、Vertical shiftタブでは水平位置を保持して垂直移動を再推定します。
- vertical_only / none：それぞれ水平移動、または両移動を固定します。固定値はlog10で指定します。

最小重なり点数、探索範囲、既存の複合損失関数のb・cをSettingsで指定できます。時間領域では探索グリッドと重なり境界を調べた後、良好な候補を局所的に精密化します。

両対数上でほぼ直線の曲線は、水平・垂直移動を同時に識別できない場合があります。重なり領域の傾きの標準偏差が0.001未満の場合は識別困難として警告し、成功扱いにしません。一方を固定して再計算してください。これは数値的な診断であり、重ね合わせの物理的妥当性や推定値の信頼区間を保証するものではありません。

表の係数をダブルクリックするか、矢印ボタンで手動調整します。入力、測定形式、条件、基準、スケールを変更した場合はApply dataで再読込します。水平シフトを変更した後は垂直シフトを再計算します。

## 出力

- `rheo_shift_factors.csv`：係数、成否、重なり点数、損失、条件、変換式。
- `rheo_horizontal_shift_factors.csv`：水平／同時推定段階の係数。
- `rheo_shifted_data.csv`：元データとシフト後のデータ。
- `analysis_metadata.json`：測定形式、条件、基準、入力スケール、係数の定義。
- `igor_trace_shift_commands.txt`：既存のトレース表示に対する移動コマンド。元のwaveを変更しません。失敗した条件はスキップします。
- 入力プレビュー、水平／同時シフト、垂直シフトのPNG。

従来の動的粘弾性CSVは読み込めます。column_names形式は温度基準のdynamicに限ります。他の条件・測定形式には上記の3行ヘッダー形式を使用してください。出力名・係数列名はv5でrheo / a_x / b_yへ変更しました。内部の旧aT・bTフィールドは既存処理との互換性のために残しています。

## 環境構築

Python 3.10以上とTkinterが必要です。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

アプリをビルドする場合は、追加で `python -m pip install pyinstaller` を実行してください。

## 起動・検証・ビルド

```bash
python launcher.py
python -m pytest -q
python -m PyInstaller --noconfirm --clean RheoSuperposition.spec
```

ビルド結果：`dist/RheoSuperposition.app`。

依存関係は`pyproject.toml`を参照してください。設定は`~/Library/Application Support/RheoSuperposition/settings.json`に保存し、新設定がない場合は旧TimeTempSuperpositionの入出力パスを読み込みます。

この公開リポジトリには現行版のソースとサンプルを収録しています。
