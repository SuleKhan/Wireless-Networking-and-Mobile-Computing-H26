"""
sat_tools - real satellites over any place on Earth, for Network_Satellite_Planning.ipynb.

    from Satellites.sat_tools import gnss_sky, plot_sky, sky_table, street_sweep
    from Satellites.sat_tools import customer_for, serve_customer, walker_shell, evaluate_shell, bridge_figure

Built on Skyfield and SGP4 (the standard orbit model for the public orbit data, "TLEs").
The orbit data is a frozen snapshot from CelesTrak (folder tle/, see SNAPSHOT_DAY): GPS, Galileo,
GLONASS, BeiDou, Starlink, OneWeb, Iridium and the geostationary belt. Staff refresh it once a year
with update_snapshot.py; students never download orbit data.
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from sgp4.api import Satrec, SatrecArray, WGS72, jday
from skyfield.api import load, wgs84

HERE = Path(__file__).parent
TLE_DIR = HERE / "tle"
C = 299_792_458.0
RE_KM = 6378.137
MU = 398600.4418                       # km^3/s^2
TS = load.timescale(builtin=True)

GNSS = {"GPS": "gps-ops", "Galileo": "galileo", "GLONASS": "glo-ops", "BeiDou": "beidou"}
GNSS_COLOURS = {"GPS": "tab:blue", "Galileo": "tab:orange", "GLONASS": "tab:red", "BeiDou": "tab:green"}
UERE_M = 3.0                           # typical range error of a phone in open sky (single frequency)


def _snapshot_day():
    eps = []
    for line in (TLE_DIR / "gps-ops.tle").read_text().splitlines():
        if line.startswith("1 "):
            yy, doy = int(line[18:20]), float(line[20:32])
            eps.append(datetime(2000 + yy, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1))
    d = max(eps)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


SNAPSHOT_DAY = _snapshot_day()


def seed_from(matriculation) -> int:
    digits = re.sub(r"\D", "", str(matriculation))
    if len(digits) < 6:
        raise ValueError("Set MATRICULATION to your matriculation number, e.g. '12-345-678'.")
    return int(hashlib.sha256(digits.encode()).hexdigest()[:8], 16)


# ----------------------------------------------------------------------------- time
def swiss_time_to_utc(local: str) -> datetime:
    """'2026-11-12 14:05' Swiss local time (CET in winter, CEST in summer) to UTC."""
    t = datetime.strptime(local.strip(), "%Y-%m-%d %H:%M")

    def last_sunday(year, month):
        d = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    start = last_sunday(t.year, 3).replace(hour=2)
    end = last_sunday(t.year, 10).replace(hour=3)
    offset = 2 if start <= t < end else 1
    return (t - timedelta(hours=offset)).replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- GNSS sky
_cache = {}


def load_group(group):
    """Skyfield satellites of one snapshot file, e.g. 'gps-ops'."""
    if group not in _cache:
        _cache[group] = load.tle_file(str(TLE_DIR / f"{group}.tle"))
    return _cache[group]


def gnss_sky(lat, lon, when_utc, height_m=400.0):
    """Azimuth and elevation of every GNSS satellite at one place and time.
    Returns {system: dict(name, az, el)} with angles in degrees."""
    place = wgs84.latlon(lat, lon, elevation_m=height_m)
    t = TS.from_datetime(when_utc)
    age = abs((when_utc - SNAPSHOT_DAY).days)
    if age > 60:
        print(f"[note] {when_utc:%Y-%m-%d} is {age} days from the orbit snapshot ({SNAPSHOT_DAY:%Y-%m-%d}); "
              "positions may be off by a few degrees.")
    sky = {}
    for system, group in GNSS.items():
        names, az, el = [], [], []
        for sat in load_group(group):
            alt, azi, _ = (sat - place).at(t).altaz()
            names.append(sat.name)
            az.append(azi.degrees)
            el.append(alt.degrees)
        sky[system] = dict(name=np.array(names), az=np.array(az), el=np.array(el))
    return sky


def street_mask(az_deg, width_m, height_m, direction_deg=0.0):
    """Elevation (deg) hidden by the buildings of a straight street.
    direction_deg: azimuth of the street axis (0 = north-south, 90 = east-west)."""
    s = np.abs(np.sin(np.radians(np.asarray(az_deg) - direction_deg)))
    dist = np.where(s > 1e-6, (width_m / 2) / np.maximum(s, 1e-6), np.inf)
    return np.degrees(np.arctan2(height_m, dist))


def dops(az_deg, el_deg):
    """Dilution of precision (PDOP, HDOP, VDOP) for satellites at these angles; inf if fewer than 4.
    One receiver clock for all systems (phones correct the offsets between systems)."""
    if len(az_deg) < 4:
        return np.inf, np.inf, np.inf
    a, e = np.radians(az_deg), np.radians(el_deg)
    G = np.column_stack([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e), np.ones_like(e)])
    try:
        Q = np.linalg.inv(G.T @ G)
    except np.linalg.LinAlgError:
        return np.inf, np.inf, np.inf
    return float(np.sqrt(Q[0, 0] + Q[1, 1] + Q[2, 2])), float(np.sqrt(Q[0, 0] + Q[1, 1])), float(np.sqrt(Q[2, 2]))


def _visible(sky, systems, min_el, street):
    az = np.concatenate([sky[s]["az"] for s in systems])
    el = np.concatenate([sky[s]["el"] for s in systems])
    ok = el > min_el
    if street:
        ok &= el > street_mask(az, **street)
    return az[ok], el[ok]


def sky_table(sky, street=None, min_el=10.0):
    """Satellites usable and expected accuracy, GPS + Galileo against all four systems,
    in open sky and (if given) in the street: street = dict(width_m=12, height_m=15, direction_deg=0)."""
    rows = []
    cases = [("open sky", None)] + ([(f"street {street['width_m']} m wide, {street['height_m']} m walls", street)] if street else [])
    for label, st in cases:
        for systems in (["GPS", "Galileo"], list(GNSS)):
            az, el = _visible(sky, systems, min_el, st)
            p, h, v = dops(az, el)
            rows.append(dict(where=label, systems=" + ".join(systems), n=len(az), pdop=p, hdop=h,
                             accuracy_m=h * UERE_M if np.isfinite(h) else np.inf))
    print(f"{'where':34s}{'systems':36s}{'sats':>5s}{'PDOP':>7s}{'HDOP':>7s}{'~accuracy':>11s}")
    for r in rows:
        acc = f"{r['accuracy_m']:7.1f} m" if np.isfinite(r["accuracy_m"]) else "  no fix"
        print(f"{r['where']:34s}{r['systems']:36s}{r['n']:5d}{r['pdop']:7.1f}{r['hdop']:7.1f}{acc:>11s}")
    print(f"(satellites above {min_el:.0f} deg and above the walls; accuracy ~ HDOP x {UERE_M:.0f} m, geometry only: "
          "reflections in a street add more)")
    return rows


def plot_sky(sky, street=None, title="GNSS satellites in view"):
    """Sky plot: centre = straight up, edge = horizon, north at the top. Grey = hidden by the street's walls."""
    fig = plt.figure(figsize=(6.2, 6.2))
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    if street:
        azm = np.linspace(0, 360, 721)
        ax.fill_between(np.radians(azm), 90 - street_mask(azm, **street), 90, color="0.75", alpha=0.7,
                        label=f"walls ({street['width_m']} m street)")
    for system, d in sky.items():
        up = d["el"] > 0
        ax.scatter(np.radians(d["az"][up]), 90 - d["el"][up], s=30, color=GNSS_COLOURS[system], label=system, zorder=3)
    ax.set_rlim(0, 90)
    ax.set_yticks([0, 30, 60, 80])
    ax.set_yticklabels(["90°", "60°", "30°", "10°"], fontsize=8)
    ax.legend(loc="lower left", bbox_to_anchor=(-0.18, -0.16), fontsize=8)
    ax.set_title(title, fontsize=10)
    plt.tight_layout()
    plt.show()


def street_sweep(lat, lon, day_utc=None, widths=(8, 10, 12, 15, 20, 25, 30), height_m=15.0, direction_deg=0.0,
                 step_min=10, min_el=10.0):
    """Over one day: share of the time with a 3D fix (>= 4 satellites) and the median PDOP,
    against the street width, for GPS + Galileo and for all four systems."""
    day_utc = day_utc or SNAPSHOT_DAY
    place = wgs84.latlon(lat, lon)
    times = TS.utc(day_utc.year, day_utc.month, day_utc.day, 0, range(0, 24 * 60, step_min))
    track = {}
    for system, group in GNSS.items():
        az, el = [], []
        for sat in load_group(group):
            alt, azi, _ = (sat - place).at(times).altaz()
            az.append(azi.degrees)
            el.append(alt.degrees)
        track[system] = (np.array(az), np.array(el))
    res = {}
    for systems in (("GPS", "Galileo"), tuple(GNSS)):
        az = np.concatenate([track[s][0] for s in systems])
        el = np.concatenate([track[s][1] for s in systems])
        fix, med = [], []
        for w in widths:
            vis = (el > min_el) & (el > street_mask(az, w, height_m, direction_deg))
            p = np.array([dops(az[vis[:, k], k], el[vis[:, k], k])[0] for k in range(az.shape[1])])
            fix.append(np.mean(vis.sum(0) >= 4) * 100)
            fin = p[np.isfinite(p)]
            med.append(float(np.median(fin)) if len(fin) else np.inf)
        res[" + ".join(systems)] = dict(fix_pct=fix, median_pdop=med)
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    for k, r in res.items():
        ax[0].plot(widths, r["fix_pct"], "o-", label=k)
        ax[1].plot(widths, np.minimum(r["median_pdop"], 50), "o-", label=k)
    ax[0].set(xlabel="street width (m)", ylabel="share of the day with >= 4 satellites (%)", ylim=(-3, 103))
    ax[1].set(xlabel="street width (m)", ylabel="median PDOP (lower is better)", yscale="log")
    for a in ax:
        a.grid(alpha=0.3, which="both")
        a.legend(fontsize=8)
    fig.suptitle(f"Street canyon, {height_m:.0f} m walls, street axis {direction_deg:.0f} deg, over {day_utc:%Y-%m-%d}", fontsize=10)
    plt.tight_layout()
    plt.show()
    print(f"{'width':>6s}" + "".join(f"{k:>34s}" for k in res))
    for i, w in enumerate(widths):
        print(f"{w:5d}m" + "".join(f"{r['fix_pct'][i]:13.0f} % fix, PDOP {r['median_pdop'][i]:6.1f}" for r in res.values()))
    return res


# ----------------------------------------------------------------------------- bulk propagation
def _satrecs(group):
    lines = (TLE_DIR / f"{group}.tle").read_text().splitlines()
    return [Satrec.twoline2rv(lines[i], lines[i + 1]) for i in range(len(lines) - 1)
            if lines[i].startswith("1 ") and lines[i + 1].startswith("2 ")]


def _gmst(jd_ut1):
    t = (jd_ut1 - 2451545.0) / 36525.0
    g = 67310.54841 + (876600 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return np.radians((g % 86400) / 240.0)


def _site_ecef(lat, lon, h_km=0.0):
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = np.radians(lat), np.radians(lon)
    n = RE_KM / np.sqrt(1 - e2 * np.sin(la) ** 2)
    return np.array([(n + h_km) * np.cos(la) * np.cos(lo), (n + h_km) * np.cos(la) * np.sin(lo), (n * (1 - e2) + h_km) * np.sin(la)])


def tracks(satrecs, lat, lon, hours=24.0, step_min=1.0, start=None, f_hz=2.0e9, chunk=120):
    """Elevation (deg), slant range (km) and Doppler (Hz at f_hz) of every satellite at every time step.
    Arrays of shape (satellites, time steps). Vectorised SGP4, fast enough for all of Starlink."""
    start = start or SNAPSHOT_DAY
    arr = SatrecArray(satrecs)
    jd0, fr0 = jday(start.year, start.month, start.day, start.hour, start.minute, start.second)
    n_t = int(round(hours * 60 / step_min))
    site = _site_ecef(lat, lon)
    up = np.array([np.cos(np.radians(lat)) * np.cos(np.radians(lon)), np.cos(np.radians(lat)) * np.sin(np.radians(lon)),
                   np.sin(np.radians(lat))])
    out_el, out_rng, out_dop = [], [], []
    for s0 in range(0, n_t, chunk):
        k = np.arange(s0, min(n_t, s0 + chunk))
        fr = fr0 + k * step_min / 1440.0
        jd = np.full_like(fr, jd0)
        err, r, v = arr.sgp4(jd, fr)                       # TEME frame, km and km/s
        th = _gmst(jd + fr)
        c, s = np.cos(th), np.sin(th)
        x, y, z = c * r[..., 0] + s * r[..., 1], -s * r[..., 0] + c * r[..., 1], r[..., 2]
        vx = c * v[..., 0] + s * v[..., 1] + 7.2921159e-5 * y
        vy = -s * v[..., 0] + c * v[..., 1] - 7.2921159e-5 * x
        dx, dy, dz = x - site[0], y - site[1], z - site[2]
        rng = np.sqrt(dx * dx + dy * dy + dz * dz)
        el = np.degrees(np.arcsin(np.clip((dx * up[0] + dy * up[1] + dz * up[2]) / rng, -1, 1)))
        el[err != 0] = -90.0
        out_el.append(el)
        out_rng.append(rng)
        out_dop.append(-(dx * vx + dy * vy + dz * v[..., 2]) / rng * 1e3 / C * f_hz)
    return np.concatenate(out_el, 1), np.concatenate(out_rng, 1), np.concatenate(out_dop, 1)


_SYSTEMS = None


def constellations():
    """The real systems in the snapshot: Starlink split by shell, OneWeb, Iridium and the true
    geostationary satellites (inclination below 1 deg). {label: dict(satrecs, min_el, note)}."""
    global _SYSTEMS
    if _SYSTEMS is None:
        star = _satrecs("starlink")
        inc = np.degrees([s.inclo for s in star])
        shells = {"Starlink 53°": (52, 54.5), "Starlink 43°": (42, 44), "Starlink 70°": (69, 71), "Starlink 97.6°": (97, 98.5)}
        _SYSTEMS = {k: dict(satrecs=[s for s, i in zip(star, inc) if lo <= i < hi], min_el=25.0, note="dish, about 470 km")
                    for k, (lo, hi) in shells.items()}
        _SYSTEMS["OneWeb"] = dict(satrecs=_satrecs("oneweb"), min_el=25.0, note="dish, 1,200 km, 88°")
        _SYSTEMS["Iridium"] = dict(satrecs=_satrecs("iridium-NEXT"), min_el=8.2, note="handheld, 780 km, 86°")
        _SYSTEMS["GEO"] = dict(satrecs=[s for s in _satrecs("geo") if np.degrees(s.inclo) < 1.0], min_el=10.0,
                               note="dish, 35,786 km")
    return _SYSTEMS


def _metrics(el, rng, dop, mask, step_min):
    vis = el > mask
    n = vis.sum(0)
    on = n > 0
    gaps, run = [0], 0
    for flag in on:
        run = 0 if flag else run + 1
        gaps.append(run)
    best = np.where(vis, el, -90).argmax(0)
    cols = np.arange(el.shape[1])
    best_el = np.where(on, el[best, cols], np.nan)
    delay = np.where(on, rng[best, cols] / C * 1e6, np.nan)                 # ms, user to satellite
    dmax = float(np.nanmax(np.abs(np.where(vis, dop, np.nan)))) / 1e3 if vis.any() else np.nan
    f = lambda a: float(np.nanmedian(a)) if np.isfinite(a).any() else np.nan
    return dict(available_pct=float(on.mean() * 100), longest_gap_min=max(gaps) * step_min, median_in_view=float(np.median(n)),
                median_best_el=f(best_el), median_delay_ms=f(delay), max_doppler_khz=dmax, in_view=n)


# ----------------------------------------------------------------------------- customers
CUSTOMERS = [
    dict(name="Alpine hut, Bernese Oberland", lat=46.55, lon=7.98, terrain_mask=20, subscribers=60, area_km2=1,
         need="guest Wi-Fi and a webcam, about 50 Mb/s in total; a dish on the roof is fine; gaps under 5 minutes"),
    dict(name="Research ship near Svalbard", lat=78.5, lon=15.0, terrain_mask=10, subscribers=40, area_km2=50000,
         need="science data and crew internet, 20 Mb/s; a dish on deck; gaps under 10 minutes",
         masts="the ship cruises the open sea; masts on the coast reach only its first few tens of km"),
    dict(name="Soil sensors, Algerian Sahara", lat=23.0, lon=5.5, terrain_mask=10, subscribers=1000, area_km2=10000,
         need="1,000 battery sensors, 200 bytes each per hour, no dish; gaps of an hour are fine"),
    dict(name="Rail line, northern Canada", lat=58.7, lon=-94.2, terrain_mask=10, subscribers=50, line_km=1000,
         need="train crews need voice and signalling at all times along 1,000 km; gaps under 1 minute"),
    dict(name="Sheep ranches, Patagonia", lat=-49.3, lon=-72.9, terrain_mask=15, subscribers=200, area_km2=5000,
         need="40 families, 20 Mb/s each at peak; dishes are fine; gaps under 5 minutes"),
    dict(name="Fishing fleet near Kiribati", lat=1.9, lon=-157.4, terrain_mask=10, subscribers=30, area_km2=100000,
         need="30 boats, weather and safety messages, 1 Mb/s each; small antennas; gaps under 5 minutes",
         masts="open ocean; masts are possible only on a few small islands"),
    dict(name="Mountain villages, Nepal Himalaya", lat=28.0, lon=86.9, terrain_mask=35, subscribers=3000, area_km2=600,
         need="schools and a health post, 20 Mb/s per village; deep valleys hide the sky below 35°"),
    dict(name="Mining camp, Australian outback", lat=-23.7, lon=133.9, terrain_mask=10, subscribers=200, area_km2=4,
         need="200 workers, video calls, 100 Mb/s in total; gaps under 1 minute"),
    dict(name="Research station Concordia, Antarctica", lat=-75.1, lon=123.3, terrain_mask=10, subscribers=15, area_km2=1,
         need="science data 10 Mb/s and a voice link for emergencies; gaps under 15 minutes",
         masts="one mast covers the station, but it would need a backhaul link over 1,000 km of ice"),
    dict(name="Hikers' phones, remote Swiss valleys", lat=46.6, lon=8.9, terrain_mask=30, subscribers=2000, area_km2=500,
         need="SOS and short messages from ordinary phones, a few kb/s each; no extra hardware"),
    dict(name="Cargo ships, Northern Sea Route", lat=75.5, lon=120.0, terrain_mask=10, subscribers=50, line_km=5600,
         need="50 ships, navigation and crew internet, 5 Mb/s each; dishes; gaps under 10 minutes",
         masts="masts would stand on an empty Arctic coast, often far from the ships' route"),
    dict(name="Village school, Amazon river", lat=-3.1, lon=-60.0, terrain_mask=20, subscribers=300, area_km2=10,
         need="a school of 300 pupils, 30 Mb/s; a dish on the roof; gaps under 5 minutes"),
]


def customer_for(matriculation):
    """Your customer, chosen by your matriculation number."""
    c = dict(CUSTOMERS[seed_from(matriculation) % len(CUSTOMERS)])
    area = c.get("area_km2") or 2 * 10 * c.get("line_km", 1)      # a line: a corridor 10 km either side
    c["density_per_km2"] = c["subscribers"] / area
    print(f"Your customer: {c['name']} ({c['lat']:.1f}°, {c['lon']:.1f}°)\n   need: {c['need']}\n"
          f"   {c['subscribers']:,} subscribers, about {c['density_per_km2']:.3g} per km²; sky hidden below {c['terrain_mask']}°")
    return c


def serve_customer(customer, hours=24.0, step_min=1.0, systems=None):
    """How each real system serves the customer over one day: availability, gaps, satellites in view,
    elevation, delay and Doppler. Plots satellites in view over the day."""
    sysd = constellations()
    systems = systems or list(sysd)
    res = {}
    for k in systems:
        s = sysd[k]
        mask = max(s["min_el"], customer["terrain_mask"])
        el, rng, dop = tracks(s["satrecs"], customer["lat"], customer["lon"], hours, step_min)
        res[k] = _metrics(el, rng, dop, mask, step_min)
        res[k].update(mask=mask, satellites=len(s["satrecs"]))
    _print_metrics(customer, res)
    names = list(res)
    grid = np.array([res[k]["in_view"] for k in names], float)
    fig, ax = plt.subplots(figsize=(10, 0.45 * len(names) + 1.4))
    im = ax.imshow(np.where(grid > 0, np.log10(grid + 1), np.nan), aspect="auto", cmap="viridis", interpolation="nearest",
                   extent=[0, hours, len(names) - 0.5, -0.5], vmin=0, vmax=2)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels([f"{k} ({res[k]['available_pct']:.0f} %)" for k in names], fontsize=8)
    ax.set_xlabel(f"hours (UTC) from {SNAPSHOT_DAY:%Y-%m-%d} 00:00; white = no satellite above the mask")
    ax.set_xticks(range(0, int(hours) + 1, 3))
    cb = fig.colorbar(im, ax=ax, pad=0.01, ticks=np.log10([2, 5, 11, 31, 101]))
    cb.ax.set_yticklabels(["1", "4", "10", "30", "100"], fontsize=7)
    cb.set_label("satellites in view", fontsize=8)
    ax.set_title(f"{customer['name']}: when each system serves (share of the day in brackets)", fontsize=10)
    plt.tight_layout()
    plt.show()
    return res


def _print_metrics(customer, res):
    print(f"{customer['name']} ({customer['lat']:.1f}°, {customer['lon']:.1f}°), one day, 1-minute steps")
    print(f"{'system':16s}{'sats':>6s}{'mask':>6s}{'available':>11s}{'longest gap':>13s}{'in view':>9s}"
          f"{'best elev.':>12s}{'delay':>9s}{'Doppler':>10s}")
    fmt = lambda v, f, unit: (f"{v:{f}}{unit}" if np.isfinite(v) else "-")
    for k, r in res.items():
        print(f"{k:16s}{r['satellites']:6d}{r['mask']:5.0f}°{r['available_pct']:10.1f}%{r['longest_gap_min']:9.0f} min"
              f"{r['median_in_view']:9.0f}{fmt(r['median_best_el'], '.1f', '°'):>12s}{fmt(r['median_delay_ms'], '.1f', ' ms'):>9s}"
              f"{fmt(r['max_doppler_khz'], '.1f', ' kHz'):>10s}")
    print("(in view, best elevation and delay are medians; delay is user to satellite, one way; "
          "Doppler is the largest at 2 GHz)")


def walker_shell(alt_km, inc_deg, planes, per_plane, phasing=1):
    """A 'what if' shell: planes x per_plane satellites on circular orbits (a Walker constellation).
    Returns SGP4 satellites for evaluate_shell()."""
    n = np.sqrt(MU / (RE_KM + alt_km) ** 3) * 60                     # rad per minute
    jd0, fr0 = jday(SNAPSHOT_DAY.year, SNAPSHOT_DAY.month, SNAPSHOT_DAY.day, 0, 0, 0)
    sats = []
    for p in range(planes):
        for s in range(per_plane):
            sat = Satrec()
            sat.sgp4init(WGS72, "i", p * per_plane + s, jd0 + fr0 - 2433281.5, 0.0, 0.0, 0.0, 1e-7, 0.0,
                         np.radians(inc_deg), 2 * np.pi * (s / per_plane + phasing * p / (planes * per_plane)), n,
                         2 * np.pi * p / planes)
            sats.append(sat)
    return sats


def evaluate_shell(customer, shell, min_el=25.0, label="what-if shell", hours=24.0, step_min=1.0):
    """The same numbers as serve_customer(), for your own shell."""
    mask = max(min_el, customer["terrain_mask"])
    el, rng, dop = tracks(shell, customer["lat"], customer["lon"], hours, step_min)
    r = _metrics(el, rng, dop, mask, step_min)
    r.update(mask=mask, satellites=len(shell))
    _print_metrics(customer, {label: r})
    return r


def orbit_basics(alt_km):
    """Period (min), speed (km/s) and footprint radius at a 25° mask (km) of a circular orbit."""
    a = RE_KM + alt_km
    period = 2 * np.pi * np.sqrt(a ** 3 / MU) / 60
    speed = np.sqrt(MU / a)
    e = np.radians(25)
    lam = np.arccos(RE_KM / a * np.cos(e)) - e                        # Earth-central angle of the footprint
    return dict(period_min=period, speed_kms=speed, footprint_radius_km=RE_KM * lam)


# ----------------------------------------------------------------------------- masts or satellites
def beam_capacity(f_hz, aperture_m, alt_km, bandwidth_hz, bits_per_hz, reuse=1):
    """One spot beam pointing straight down: its area (km2), capacity (Mb/s) and capacity per km2."""
    theta = 1.02 * (C / f_hz) / aperture_m                              # 3 dB beamwidth (rad)
    area = np.pi * (alt_km * np.tan(theta / 2)) ** 2
    cap = bandwidth_hz / reuse * bits_per_hz / 1e6
    return dict(beam_area_km2=area, beam_mbps=cap, mbps_per_km2=cap / area)


DISH_BEAM = dict(f_hz=11.7e9, aperture_m=1.0, alt_km=470, bandwidth_hz=2e9, bits_per_hz=3.0, reuse=4)
PHONE_BEAM = dict(f_hz=1.9e9, aperture_m=5.0, alt_km=470, bandwidth_hz=5e6, bits_per_hz=1.0, reuse=1)


def constellation_average(n_sats, gbps_per_sat=80.0, max_lat_deg=60.0):
    """Average capacity per km2 if every satellite's capacity is spread over the band of latitudes
    the constellation serves (an upper bound: much of it lies over oceans)."""
    area = 4 * np.pi * RE_KM ** 2 * np.sin(np.radians(max_lat_deg))
    return n_sats * gbps_per_sat * 1e3 / area


def masts_needed(customer, mast_m=30.0):
    """Masts to cover the customer, each reaching its radio horizon (optimistic: hills and the link budget
    shorten it). Every mast also needs power and a backhaul link."""
    from math import sqrt
    reach = 4.12 * (sqrt(mast_m) + sqrt(1.5))
    if customer.get("line_km"):
        n = int(np.ceil(customer["line_km"] / (2 * reach * 0.8)))
    else:
        n = int(max(1, np.ceil(customer.get("area_km2", 1) / (2.6 * reach ** 2))))
    return dict(reach_km=reach, masts=n, note=customer.get("masts", ""))


def bridge_figure(customer=None, my_sites_per_km2=None, n_sats=None, gbps_per_sat=80.0):
    """Masts against satellites on one picture, with the cellular numbers of Part 1 (Cellular.cellular_tools)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    from Cellular.cellular_tools import knee_curves
    k = knee_curves()
    users = k["users"]
    dish = beam_capacity(**DISH_BEAM)
    phone = beam_capacity(**PHONE_BEAM)
    n_sats = n_sats or len(constellations()["Starlink 53°"]["satrecs"]) + len(constellations()["Starlink 43°"]["satrecs"])
    avg = constellation_average(n_sats, gbps_per_sat)
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    a = ax[0]
    a.loglog(users, users * k["per_sub_mbps"], "k-", lw=2, label=f"demand ({k['per_sub_mbps']} Mb/s per subscriber)")
    a.axhline(dish["mbps_per_km2"], color="tab:purple", lw=2, label=f"one dish beam, peak: {dish['mbps_per_km2']:.2g} Mb/s/km²")
    a.axhline(avg, color="tab:purple", lw=1.5, ls="--", label=f"{n_sats:,} satellites, average: {avg:.2g} Mb/s/km²")
    a.axhline(phone["mbps_per_km2"], color="tab:brown", lw=2, label=f"one direct-to-phone beam: {phone['mbps_per_km2']:.2g} Mb/s/km²")
    floor_r = k["coverage_floor"]["rural"] * k["cap_site_mbps"][700]
    a.axhline(floor_r, color="tab:green", lw=1.5, ls=":", label=f"rural 700 MHz masts, coverage floor: {floor_r:.2g} Mb/s/km²")
    if customer:
        a.axvline(customer["density_per_km2"], color="tab:red", lw=1.5, ls="-.", label=f"your customer: {customer['density_per_km2']:.3g}/km²")
    a.set(xlabel="subscribers per km²", ylabel="capacity per km² (Mb/s)", ylim=(1e-4, 1e4), xlim=(1e-2, 1e5))
    a.set_title("What satellites can carry, against the demand", fontsize=10)
    a.grid(alpha=0.3, which="both")
    a.legend(fontsize=7, loc="upper left")
    b = ax[1]
    b.loglog(users, k["sites_700_rural"], color="tab:green", lw=1.5, ls="--", label="700 MHz, rural, outdoor phones")
    b.loglog(users, k["sites_700"], color="tab:blue", lw=2, label="700 MHz, indoor phones")
    b.loglog(users, k["sites_3500"], color="tab:red", lw=2, label="3.5 GHz, indoor phones")
    for lim, col, name in ((dish["mbps_per_km2"] / k["per_sub_mbps"], "tab:purple", "one dish beam is enough"),
                           (phone["mbps_per_km2"] / k["per_sub_mbps"], "tab:brown", "one phone beam is enough")):
        b.axvspan(1e-2, lim, color=col, alpha=0.08)
        b.text(lim / 1.15, 2e-3, name, rotation=90, ha="right", va="bottom", fontsize=8, color=col)
    if customer:
        b.axvline(customer["density_per_km2"], color="tab:red", lw=1.5, ls="-.", label="your customer")
    if my_sites_per_km2:
        b.axhline(my_sites_per_km2, color="0.3", lw=1, ls="--", label="your tram-ride estimate (Part 1)")
    b.set(xlabel="subscribers per km²", ylabel="mast sites per km²", ylim=(1e-3, 1e3), xlim=(1e-2, 1e5))
    b.set_title("What masts need (Part 1)", fontsize=10)
    b.grid(alpha=0.3, which="both")
    b.legend(fontsize=7, loc="upper left")
    plt.tight_layout()
    plt.show()
    print(f"one dish beam: {dish['beam_area_km2']:.0f} km², {dish['beam_mbps']:.0f} Mb/s, {dish['mbps_per_km2']:.2f} Mb/s/km² "
          f"-> up to {dish['mbps_per_km2'] / k['per_sub_mbps']:.0f} subscribers per km²")
    print(f"one direct-to-phone beam: {phone['beam_area_km2']:.0f} km², {phone['beam_mbps']:.0f} Mb/s, "
          f"{phone['mbps_per_km2']:.3f} Mb/s/km² -> up to {phone['mbps_per_km2'] / k['per_sub_mbps']:.2f} subscribers per km²")
    print(f"{n_sats:,} satellites x {gbps_per_sat:.0f} Gb/s spread over latitudes up to 60°: {avg:.2f} Mb/s/km² on average")
    print(f"rural masts (700 MHz, {k['r_rural_km']:.1f} km reach): coverage floor {floor_r:.2f} Mb/s/km², knee at "
          f"{k['knee']['rural']:.1f} subscribers per km²")
    return dict(dish=dish, phone=phone, average=avg, knee=k["knee"], rural_floor=floor_r)


def next_passes(lat, lon, name="ISS (ZARYA)", days=3, min_el=20.0):
    """Optional: when a station or satellite from tle/stations.tle passes over (UTC)."""
    sat = {s.name.strip(): s for s in load_group("stations")}[name]
    place = wgs84.latlon(lat, lon)
    t0 = TS.from_datetime(SNAPSHOT_DAY)
    t, events = sat.find_events(place, t0, t0 + days, altitude_degrees=min_el)
    print(f"{name} above {min_el:.0f}° (UTC; add 1 h for Swiss winter time, 2 h in summer):")
    for ti, ev in zip(t, events):
        if ev == 1:
            alt = (sat - place).at(ti).altaz()[0].degrees
            print(f"   {ti.utc_strftime('%Y-%m-%d %H:%M')}  highest point {alt:.0f}°")
