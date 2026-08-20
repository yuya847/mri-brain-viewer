# MRI Viewer

DICOM を JPEG に事前変換して、**ブラウザだけで PACS のようにスライスを送れる**ビューアです。
サーバーもライブラリも使いません。HTML と canvas だけで動きます。

**デモ → https://yuya847.github.io/mri-brain-viewer/**

収録しているのは匿名化した頭部 MRI 1 例（Philips Prodiva CS, 6 シリーズ 251 枚）です。
患者 ID・年齢・撮像日は含めていません。

## 操作

| PC | 動作 |
|---|---|
| ホイール / ↑↓ | スライス送り（マウス 1 ノッチ = 1 枚） |
| 左ドラッグ | ツールバーで選んだツール（既定は階調 W/L） |
| 右ドラッグ | 拡大縮小 |
| 中ドラッグ / Shift+ドラッグ | 画像移動 |
| Space | シネ再生（fps 可変） |
| 1〜6 / R / I / F | シリーズ切替 / リセット / 白黒反転 / 全画面 |
| 計測ツール | ドラッグで距離（PixelSpacing から mm 表示） |

| iPhone・iPad | 動作 |
|---|---|
| 1 本指で上下スワイプ | スライス送り（画面の上端→下端で 1 シリーズ分） |
| 2 本指ピンチ・ドラッグ | 拡大縮小・移動 |
| ダブルタップ | 全体表示 ⇄ 等倍 |
| 「⤢ 全画面」 | UI を隠して画像だけにする（✕ で戻る） |

## 2 つの配布形態

| | 中身 | 向いている用途 |
|---|---|---|
| `index.html` + `images/` | 画像を分割配信 | Web に置く。初回表示が速い |
| `MRI_case01.html` | 画像を data URL で全部埋め込んだ 1 ファイル（10.7 MB） | AirDrop・メール・USB で渡す。**オフラインで開ける** |

単一ファイル版は iPhone に AirDrop → 「"ファイル" に保存」→ タップするだけで開きます。

## 自分の DICOM で使う

```bash
python3 -m venv .venv
.venv/bin/pip install pydicom pylibjpeg pylibjpeg-libjpeg numpy pillow

mkdir dicom && cp /path/to/your/*.dcm dicom/     # DICOM を置く

# 手元用（原寸・患者情報あり）: images/ と index.html を更新
.venv/bin/python convert.py

# 配布用 1 ファイル（既定で匿名化）
.venv/bin/python build_single.py --label "Case 01" --out MRI_case01.html

# Web 用フォルダ版（匿名化）
.venv/bin/python build_single.py --label "Case 01" --web-dir web-build
```

`build_single.py` の主なオプション

| オプション | 意味 |
|---|---|
| `--label` | 患者情報の代わりに出す表示名 |
| `--max` | 長辺の最大画素数（既定 560）。420 にすると 6 MB 台まで落ちる |
| `--quality` | JPEG 品質（既定 82） |
| `--keep-id` | 患者 ID・性別年齢・撮像日を残す（自分用） |
| `--web-dir` | フォルダ版を出力 |

`.gitignore` で `dicom/` と `manifest.json`（患者情報を含む）を除外しています。

## しくみ

- DICOM を pydicom で読み、RescaleSlope/Intercept を適用してから
  **既定ウィンドウ（WindowCenter ± WindowWidth）の範囲を 8bit へ線形に写して** JPEG 化します。
  ビューア側の W/L 調整はこの範囲内で効きます。
- 表示は canvas 1 枚。W/L は `ctx.filter = brightness() contrast()` に落として GPU に任せているので、
  スライスを高速に送っても軽いままです。
- デコード済み画像は LRU で上限を設けています（埋め込み版は 90 枚）。スマホでメモリを使い切らないため。
- 縮小したときは PixelSpacing を補正するので、計測の mm 値はずれません。

## 注意

診断用ではありません。閲覧・供覧・教育用です。厳密な読影は元の DICOM を正規のビューアでご覧ください。

## License

MIT
