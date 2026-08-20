#!/usr/bin/env python3
"""dicom/ から「配布用の 1 ファイル HTML」を作る。

  .venv/bin/python build_single.py --label "Case 01" --out MRI_case01.html

画像を data URL として index.html に埋め込むので、出来上がった HTML 1 個を
AirDrop / メール / USB で渡すだけで、オフラインのまま iPhone でも PC でも開けます。
既定で患者情報（ID・性別・年齢・撮像日）を落とします（--keep-id で残す）。
"""
import argparse, base64, glob, io, json, os, sys
import numpy as np
import pydicom
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "dicom")


def val(x, default=None):
    if x is None:
        return default
    if isinstance(x, (list, pydicom.multival.MultiValue)):
        x = x[0]
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def jpeg_data_url(arr, quality):
    buf = io.BytesIO()
    Image.fromarray(arr, mode="L").save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="MRI_shared.html", help="出力 HTML")
    ap.add_argument("--label", default="Case 01", help="患者情報の代わりに出す表示名")
    ap.add_argument("--max", type=int, default=560, help="長辺の最大画素数（縮小してファイルを軽くする）")
    ap.add_argument("--quality", type=int, default=82, help="JPEG 品質")
    ap.add_argument("--keep-id", action="store_true", help="患者 ID・年齢・撮像日を残す")
    ap.add_argument("--web-dir", help="指定するとフォルダ版（index.html + images/）をここに出力する。"
                                      "Web に置くときはこちらの方が初回表示が速い")
    args = ap.parse_args()
    web = args.web_dir and os.path.join(BASE, args.web_dir)
    if web:
        os.makedirs(web, exist_ok=True)

    files = sorted(glob.glob(os.path.join(SRC, "*")))
    if not files:
        sys.exit(f"DICOM が見つかりません: {SRC}")

    series = {}
    for f in files:
        ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
        series.setdefault(getattr(ds, "SeriesInstanceUID", "?"), []).append(f)

    first = pydicom.dcmread(files[0], stop_before_pixels=True, force=True)
    patient = {"modality": str(getattr(first, "Modality", "")),
               "study": str(getattr(first, "StudyDescription", "")),
               "device": f"{getattr(first,'Manufacturer','')} {getattr(first,'ManufacturerModelName','')}".strip()}
    if args.keep_id:
        patient.update(id=str(getattr(first, "PatientID", "")),
                       sex=str(getattr(first, "PatientSex", "")),
                       age=str(getattr(first, "PatientAge", "")),
                       date=str(getattr(first, "StudyDate", "")))
    else:
        patient["label"] = args.label          # 匿名化: ID/年齢/撮像日は入れない

    manifest = {"patient": patient, "series": []}
    slice_data = []

    for uid, paths in sorted(series.items(),
                             key=lambda kv: val(getattr(pydicom.dcmread(kv[1][0], stop_before_pixels=True,
                                                                        force=True), "SeriesNumber", 0), 0)):
        loaded = [pydicom.dcmread(p, force=True) for p in paths]

        def key(ds):
            n = val(getattr(ds, "InstanceNumber", None))
            return n if n is not None else float(getattr(ds, "ImagePositionPatient", [0, 0, 0])[2])

        loaded.sort(key=key)
        ds0 = loaded[0]
        snum = int(val(getattr(ds0, "SeriesNumber", 0), 0))
        desc = str(getattr(ds0, "SeriesDescription", f"Series {snum}")).strip()

        stack = np.stack([d.pixel_array.astype(np.float32) * val(getattr(d, "RescaleSlope", 1), 1)
                          + val(getattr(d, "RescaleIntercept", 0), 0) for d in loaded])
        smin, smax = float(stack.min()), float(stack.max())
        wc, ww = val(getattr(ds0, "WindowCenter", None)), val(getattr(ds0, "WindowWidth", None))
        if wc is None or ww is None or ww <= 0:
            wc = float(np.percentile(stack, 50))
            ww = float(np.percentile(stack, 99.5) - np.percentile(stack, 1)) or 1.0
        lo, hi = max(smin, wc - ww), min(smax, wc + ww)
        if hi - lo < 1e-6:
            lo, hi = smin, max(smax, smin + 1)
        scaled = np.clip((stack - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)

        # 縮小率（長辺 args.max まで）。等倍以上には拡大しない
        h, w = scaled.shape[1], scaled.shape[2]
        f = min(1.0, args.max / max(h, w))
        nw, nh = max(1, round(w * f)), max(1, round(h * f))

        sdir = os.path.join(web, "images", f"s{snum}") if web else None
        if sdir:
            os.makedirs(sdir, exist_ok=True)

        urls, nbytes = [], 0
        for i in range(scaled.shape[0]):
            img = Image.fromarray(scaled[i], mode="L")
            if f < 1.0:
                img = img.resize((nw, nh), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=args.quality, optimize=True)
            nbytes += buf.tell()
            if sdir:
                open(os.path.join(sdir, f"{i:04d}.jpg"), "wb").write(buf.getvalue())
            else:
                urls.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
        if not sdir:
            slice_data.append(urls)

        th = Image.fromarray(scaled[len(scaled) // 2], mode="L")
        th.thumbnail((110, 110))

        ps = getattr(ds0, "PixelSpacing", None)
        sp = (val(ps[0]) / f) if ps else None      # 縮小した分だけ 1 画素の実寸は大きくなる
        entry = {
            "num": snum, "desc": desc, "count": len(loaded), "rows": nh, "cols": nw,
            "wc": round((wc - lo) / (hi - lo) * 255.0, 2), "ww": round(ww / (hi - lo) * 255.0, 2),
            "pixelSpacing": [sp, sp], "thickness": val(getattr(ds0, "SliceThickness", None)),
            "spacing": val(getattr(ds0, "SpacingBetweenSlices", None)),
            "tr": val(getattr(ds0, "RepetitionTime", None)), "te": val(getattr(ds0, "EchoTime", None)),
        }
        if sdir:
            th.save(os.path.join(sdir, "thumb.jpg"), quality=80)
            entry["dir"] = f"images/s{snum}"
        else:
            entry["thumb"] = jpeg_data_url(np.asarray(th), 78)
        manifest["series"].append(entry)
        print(f"S{snum:>3} {desc:<24} {len(loaded):>3}枚  {nw}x{nh}  {nbytes/1e6:.1f} MB", flush=True)

    # index.html をテンプレートにして、マニフェストと画像を流し込む
    html = open(os.path.join(BASE, "index.html"), encoding="utf-8").read()
    a, b = "/*MANIFEST_START*/", "/*MANIFEST_END*/"
    i, j = html.find(a), html.find(b)
    if i < 0 or j <= i:
        sys.exit("index.html に MANIFEST マーカーが見つかりません")
    block = a + "\nconst MANIFEST = " + json.dumps(manifest, ensure_ascii=False) + ";\n"
    if not web:
        block += "const SLICE_DATA = " + json.dumps(slice_data) + ";\n"
    html = html[:i] + block + html[j:]

    out = os.path.join(web, "index.html") if web else os.path.join(BASE, args.out)
    open(out, "w", encoding="utf-8").write(html)
    print(f"\n{out}  {os.path.getsize(out)/1e6:.1f} MB")
    if not args.keep_id:
        print("患者 ID / 性別年齢 / 撮像日 は含めていません（表示名: %s）" % args.label)


if __name__ == "__main__":
    main()
