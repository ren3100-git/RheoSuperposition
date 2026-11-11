# RheoSuperposition

動的粘弾性、応力緩和、クリープのデータを、指定した基準条件に重ね合わせるGUIアプリケーションです。シフト係数、重ね合わせ後のデータ、グラフを出力できます。

## ダウンロードと起動

[ダウンロードページ](https://github.com/ren3100-git/RheoSuperposition/releases/latest)のAssetsからmacOS用ZIPをダウンロードし、展開したアプリを開いてください。配布アプリの実行にPythonのインストールは不要です。

配布アプリはApple Silicon（arm64）用です。Intel Macおよび別端末での動作は未確認です。Appleによる公証は未確認で、macOSのセキュリティ機能により起動が制限される場合があります。

## 基本的な使い方

1. 「Measurement」で測定形式を選択します。
2. 「New template」で入力表を作成し、条件ごとにデータを貼り付けます。
3. 「Settings」で入力スケール、条件の名前・単位、シフト方法を設定し、「Reference condition」に基準条件を指定します。
4. 「Apply data」で入力を反映します。
5. 水平シフトを実行し、必要に応じて「Run vertical shift」で垂直シフトを実行します。グラフと係数を確認し、必要な場合は手動調整します。
6. 解析結果とグラフを出力します。

入力データや基準条件を変更した場合は、再度「Apply data」で反映してください。

## 入力データ

| Measurement | 測定形式 | 1条件あたりの列 |
|---|---|---|
| dynamic | 動的粘弾性 | w（角周波数）, G1（貯蔵弾性率）, G2（損失弾性率） |
| relaxation | 応力緩和 | t（時間）, G（緩和弾性率） |
| creep | クリープ | t（時間）, J（クリープコンプライアンス） |

入力表の先頭3行はCond（条件）、val（変数名）、name（データ名）です。その次の行から数値を入力し、各条件で同じ列構成を繰り返します。

入力スケールの初期値はlog10です。実数値を入力する場合はlinearに変更してください。この設定は横軸と応答値の両方に適用されます。

実数値としてゼロ以下の横軸・応答値は使用できません。条件内で値が欠損している行は、その条件のデータの組をまとめて解析から除外します。各条件に4点以上の異なる横軸値が必要です。

条件には温度、濃度、圧力などの数値、または文字ラベルを使用できます。条件名と単位はSettingsで指定します。

## サンプルで試す

[examples](examples)に応力緩和とクリープの人工データがあります。ファイルに対応するMeasurementを選び、次の設定を使用します。

- Input scale：linear
- Condition name：Concentration
- Unit：%
- Reference condition：1
- Shift mode：both

## シフト係数の意味

```text
x_shifted = x × a_x
response_shifted = response × b_y
```

xはdynamicでは角周波数、relaxationとcreepでは時間です。基準条件のa_xとb_yは1です。時間に対してt_reduced = t / a_Tと定義する場合、本アプリの係数はa_x = 1 / a_Tとなります。

horizontal_onlyは水平のみ、vertical_onlyは垂直のみ、bothは両方を推定します。時間領域の初期設定はhorizontal_onlyです。dynamicではtan δから水平シフト、G′・G″から垂直シフトを推定します。

両対数上でほぼ直線のデータでは、水平・垂直シフトを同時に識別できない場合があります。警告が表示された場合は、一方を固定して再計算してください。計算結果の物理的妥当性は利用者が確認してください。

## 出力

- シフト係数、推定の成否、条件を記録したCSV。
- 元データと重ね合わせ後のデータを記録したCSV。
- 解析条件と変換式を記録したanalysis_metadata.json。
- 入力データと重ね合わせ結果のPNG。
- IGOR上の既存トレースを移動するコマンド。元のwaveは変更しません。

## ソースコードから起動する場合

Python 3.10以上とTkinterが必要です。リポジトリをダウンロードし、そのフォルダ内で以下を実行します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python launcher.py
```

## 開発・配布および免責事項

本ソフトウェアは個人が開発・配布しています。開発者はApple Developer Programに登録していません。本ソフトウェアは現状のまま提供され、動作、正確性、特定の目的への適合性を保証しません。利用は利用者自身の責任で行ってください。法令上認められる範囲において、開発者は本ソフトウェアの利用または利用不能により生じた損害、データの損失その他の不利益について責任を負いません。

This software is developed and distributed by an individual developer who is not enrolled in the Apple Developer Program. It is provided as is, without warranties regarding its operation, accuracy, or fitness for a particular purpose. Use of the software is at the user’s own risk. To the extent permitted by applicable law, the developer accepts no liability for damages, data loss, or other adverse consequences arising from the use of, or inability to use, the software.
