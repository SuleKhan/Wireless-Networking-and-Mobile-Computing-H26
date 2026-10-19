"""
build_districts - staff script: rebuilds districts.npz from Swiss federal open data.

Students never run this; they only use the frozen districts.npz next to it.

    python build_districts.py            # downloads about 60 MB, writes districts.npz (about 150 KB)
    python build_districts.py raw/       # uses files already downloaded into raw/

For every district it stores a 5 x 5 km tile on the 100 m hectare grid of the
Federal Statistical Office (BFS), in Swiss coordinates (LV95, EPSG:2056):
  pop      residents per hectare (STATPOP 2024)
  fte      full-time jobs per hectare (STATENT 2023)
  bld      buildings per hectare (GWS 2024)
  inst_xy  real outdoor macro installations (> 6 W ERP) from OFCOM, antennas within 30 m merged
  small_xy real outdoor small cells (<= 6 W ERP) from OFCOM
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

BASE = "https://data.geo.admin.ch/"
SOURCES = {
    "pop": "ch.bfs.volkszaehlung-bevoelkerungsstatistik_einwohner/volkszaehlung-bevoelkerungsstatistik_einwohner_2024/volkszaehlung-bevoelkerungsstatistik_einwohner_2024_2056.csv",
    "fte": "ch.bfs.betriebszaehlungen-beschaeftigte_vollzeitaequivalente/betriebszaehlungen-beschaeftigte_vollzeitaequivalente_2023/betriebszaehlungen-beschaeftigte_vollzeitaequivalente_2023_2056.csv",
    "bld": "ch.bfs.volkszaehlung-gebaeudestatistik_gebaeude/volkszaehlung-gebaeudestatistik_gebaeude_2024/volkszaehlung-gebaeudestatistik_gebaeude_2024_2056.csv",
    "sites": "ch.bakom.standorte-mobilfunkanlagen/standorte-mobilfunkanlagen/standorte-mobilfunkanlagen_2056.json",
}
# name: (east, north) of the tile's centre in LV95; tiles are W x W hectares
DISTRICTS = {
    "Zurich": (2683000, 1247500),
    "Bern": (2600000, 1199700),
    "Basel": (2611500, 1267000),
    "Geneva": (2500000, 1118300),
    "Lausanne": (2538000, 1152400),
    "Winterthur": (2697000, 1261800),
    "Lucerne": (2666200, 1211500),
    "St. Gallen": (2746000, 1254300),
}
W = 50          # 50 x 100 m = 5 km
RES = 100


def fetch(key, raw_dir):
    name = Path(SOURCES[key]).name
    if raw_dir and (Path(raw_dir) / name).exists():
        return (Path(raw_dir) / name).read_bytes()
    print(f"downloading {name} ...")
    return urllib.request.urlopen(BASE + SOURCES[key], timeout=300).read()


def hectare_grid(text, e0, n0):
    g = np.zeros((W, W), np.float32)
    for line in text.splitlines()[1:]:
        r = line.split(";")
        e, n = int(r[1]), int(r[2])
        i, j = (n - n0) // RES, (e - e0) // RES
        if 0 <= i < W and 0 <= j < W:
            g[i, j] = float(r[3].replace(",", "."))
    return g


def merge_installations(points, radius=30.0):
    inst = []
    for x, y in points:
        for p in inst:
            if (p[0] - x) ** 2 + (p[1] - y) ** 2 < radius ** 2:
                break
        else:
            inst.append([x, y])
    return np.array(inst, np.float32).reshape(-1, 2)


def main(raw_dir=None):
    texts = {k: fetch(k, raw_dir).decode("utf-8") for k in ("pop", "fte", "bld")}
    sites = json.loads(fetch("sites", raw_dir))["features"]
    out = {"names": np.array(list(DISTRICTS))}
    for k, (name, (ec, nc)) in enumerate(DISTRICTS.items()):
        e0, n0 = ec - W * RES // 2, nc - W * RES // 2
        grids = {key: hectare_grid(texts[key], e0, n0) for key in texts}
        macro, small = [], []
        for f in sites:
            x, y = f["geometry"]["coordinates"]
            if not (e0 <= x < e0 + W * RES and n0 <= y < n0 + W * RES):
                continue
            typ = f["properties"]["typ_en"]
            if typ == "Outdoor > 6 Werp":
                macro.append((x - e0, y - n0))
            elif typ.startswith("Outdoor") and "6 Werp" in typ:
                small.append((x - e0, y - n0))
        inst = merge_installations(macro)
        for key, g in grids.items():
            out[f"{k}_{key}"] = g
        out[f"{k}_inst_xy"] = inst
        out[f"{k}_small_xy"] = np.array(small, np.float32).reshape(-1, 2)
        out[f"{k}_origin"] = np.array([e0, n0])
        print(f"{name:11s} residents {grids['pop'].sum():8,.0f}  jobs {grids['fte'].sum():8,.0f}  "
              f"buildings {grids['bld'].sum():6,.0f}  macro installations {len(inst):3d}  small cells {len(small):3d}")
    dest = Path(__file__).with_name("districts.npz")
    np.savez_compressed(dest, **out)
    print(f"wrote {dest} ({dest.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
