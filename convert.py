#!/usr/bin/env python3
"""DICOM -> JPEG + manifest.json  (MRI viewer 用)"""
import glob, json, os, sys
import numpy as np
import pydicom
from PIL import Image

SRC = os.path.join(os.path.dirname(__file__), "dicom")
OUT = os.path.join(os.path.dirname(__file__), "images")
QUALITY = 90


def val(x, default=None):
    """MultiValue や DSfloat を素の float に"""
    if x is None:
        return default
    if isinstance(x, (list, pydicom.multival.MultiValue)):
        x = x[0]
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*")))
    series = {}
    for f in files:
        ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
        uid = getattr(ds, "SeriesInstanceUID", "?")
        series.setdefault(uid, []).append((f, ds))

    manifest = {"patient": {}, "series": []}
    first = next(iter(series.values()))[0][1]
    manifest["patient"] = {
        "id": str(getattr(first, "PatientID", "")),
        "sex": str(getattr(first, "PatientSex", "")),
        "age": str(getattr(first, "PatientAge", "")),
        "study": str(getattr(first, "StudyDescription", "")),
        "date": str(getattr(first, "StudyDate", "")),
        "modality": str(getattr(first, "Modality", "")),
        "device": f"{getattr(first,'Manufacturer','')} {getattr(first,'ManufacturerModelName','')}".strip(),
    }

    os.makedirs(OUT, exist_ok=True)
    for uid, items in sorted(series.items(), key=lambda kv: val(getattr(kv[1][0][1], "SeriesNumber", 0), 0)):
        # スライス順: InstanceNumber -> 位置
        def sortkey(it):
            ds = it[1]
            n = val(getattr(ds, "InstanceNumber", None))
            if n is not None:
                return n
            ipp = getattr(ds, "ImagePositionPatient", [0, 0, 0])
            return float(ipp[2])

        items.sort(key=sortkey)
        ds0 = items[0][1]
        snum = int(val(getattr(ds0, "SeriesNumber", 0), 0))
        desc = str(getattr(ds0, "SeriesDescription", f"Series {snum}")).strip()
        sdir = os.path.join(OUT, f"s{snum}")
        os.makedirs(sdir, exist_ok=True)

        # 1st pass: 実数値化してレンジ決定
        arrays = []
        for f, _ in items:
            ds = pydicom.dcmread(f, force=True)
            a = ds.pixel_array.astype(np.float32)
            sl = val(getattr(ds, "RescaleSlope", 1), 1)
            ic = val(getattr(ds, "RescaleIntercept", 0), 0)
            arrays.append(a * sl + ic)
        stack = np.stack(arrays)
        smin, smax = float(stack.min()), float(stack.max())
        wc = val(getattr(ds0, "WindowCenter", None))
        ww = val(getattr(ds0, "WindowWidth", None))
        if wc is None or ww is None or ww <= 0:
            wc = float(np.percentile(stack, 50))
            ww = float(np.percentile(stack, 99.5) - np.percentile(stack, 1)) or 1.0
        # 既定ウィンドウの ±1WW 分を 8bit に載せる（JS 側で階調を触っても破綻しない範囲）
        lo = max(smin, wc - ww)
        hi = min(smax, wc + ww)
        if hi - lo < 1e-6:
            lo, hi = smin, max(smax, smin + 1)

        scaled = np.clip((stack - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
        for i in range(scaled.shape[0]):
            Image.fromarray(scaled[i], mode="L").save(
                os.path.join(sdir, f"{i:04d}.jpg"), quality=QUALITY, optimize=True
            )
        # サムネイル
        mid = scaled[len(scaled) // 2]
        th = Image.fromarray(mid, mode="L")
        th.thumbnail((120, 120))
        th.save(os.path.join(sdir, "thumb.jpg"), quality=80)

        ps = getattr(ds0, "PixelSpacing", None)
        manifest["series"].append({
            "num": snum,
            "desc": desc,
            "dir": f"images/s{snum}",
            "count": len(items),
            "rows": int(getattr(ds0, "Rows", 0)),
            "cols": int(getattr(ds0, "Columns", 0)),
            # 8bit 空間に写した既定 window center / width
            "wc": round((wc - lo) / (hi - lo) * 255.0, 2),
            "ww": round(ww / (hi - lo) * 255.0, 2),
            "pixelSpacing": [val(ps[0]) if ps else None, val(ps[1]) if ps else None],
            "thickness": val(getattr(ds0, "SliceThickness", None)),
            "spacing": val(getattr(ds0, "SpacingBetweenSlices", None)),
            "tr": val(getattr(ds0, "RepetitionTime", None)),
            "te": val(getattr(ds0, "EchoTime", None)),
            "orientation": [val(v) for v in getattr(ds0, "ImageOrientationPatient", [])] or None,
            "seriesTime": str(getattr(ds0, "SeriesTime", "")),
        })
        print(f"S{snum:>3} {desc:<24} {len(items):>3} slices  range=[{lo:.1f},{hi:.1f}]", flush=True)

    base = os.path.dirname(__file__)
    with open(os.path.join(base, "manifest.json"), "w") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=1)

    # index.html にマニフェストを直接埋め込む（file:// で開いても動くように）
    html_path = os.path.join(base, "index.html")
    if os.path.exists(html_path):
        html = open(html_path, encoding="utf-8").read()
        a, b = "/*MANIFEST_START*/", "/*MANIFEST_END*/"
        i, j = html.find(a), html.find(b)
        if i >= 0 and j > i:
            block = f"{a}\nconst MANIFEST = {json.dumps(manifest, ensure_ascii=False)};\n"
            html = html[:i] + block + html[j:]
            open(html_path, "w", encoding="utf-8").write(html)
            print("embedded manifest -> index.html")
    print("done ->", OUT)


if __name__ == "__main__":
    main()
