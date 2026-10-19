"""
cellular_tools - the models behind Network_Cellular.ipynb.

    from Cellular.cellular_tools import link_budget, plot_sinr_vs_spacing, compare_reuse, plot_knee

One cell:   link_budget()        downlink and uplink, 700 MHz vs 3.5 GHz, building entry, NISV cap
Many cells: median_sinr()        SINR of indoor users in a hexagonal network of 3-sector sites
            compare_reuse()      reuse 1 (LTE/5G) against reuse 3 (the classic "colours")
Planning:   knee_curves()        sites per km2 needed: coverage-limited (flat) vs capacity-limited (rising)
Your phone: path_loss_from_rsrp(), uma_distance_m(), building_entry_loss(), spacing_from_ride()

Every number below is a stated teaching assumption, typical for a Swiss macro network;
real networks differ site by site. numpy and matplotlib only.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------------- assumptions
P_BS_DBM = 46.0        # base station power per sector and carrier (40 W)
G_BS_DBI = 17.0        # sector antenna gain
FEEDER_DB = 2.0        # cable and connector loss
P_UE_DBM = 23.0        # phone transmit power (200 mW), the same in every band
NF_UE_DB = 7.0         # phone noise figure
NF_BS_DB = 3.0         # base station noise figure
SNR_MIN_DB = -5.0      # lowest SNR at which a link still carries data (robust coding)
B_UL_EDGE_HZ = 1e6     # uplink bandwidth a phone at the cell edge gets (a few resource blocks)
PER_SUB_MBPS = 0.2     # busy-hour average demand per subscriber
MARKET_SHARE = 0.25    # share of all people that are customers of "your" operator
MAST_M = 30.0          # rural mast height

BANDS = {
    700: dict(name="700 MHz (n28, FDD)", f_ghz=0.7, b_dl=10e6, b_eff=10e6, bf_dl=0.0, bf_ul=0.0, tdd_ul=0.0),
    3500: dict(name="3.5 GHz (n78, TDD)", f_ghz=3.5, b_dl=100e6, b_eff=75e6, bf_dl=10.0, bf_ul=5.0, tdd_ul=6.0),
}
# b_eff: bandwidth available for downlink traffic (TDD: 75 % of the time is downlink)
# bf_dl, bf_ul: beamforming gain of a 3.5 GHz adaptive antenna (64 sub-arrays) over a passive sector antenna
# tdd_ul: the uplink only has 25 % of the time on TDD, which costs about 6 dB at the cell edge

# NISV (Swiss ordinance on non-ionising radiation), Annex 1: installation limit values (V/m)
E_LIMIT_VM = {"700": 4.0, "3500": 6.0, "both": 5.0}
K_AA = 0.10            # correction factor for adaptive antennas with >= 64 sub-arrays (BAFU, 2021)
VERTICAL_ATT_DB = 6.0  # the main beam points over the nearest flat; vertical pattern attenuation

SWISS_BANDS = {        # 3GPP band numbers used in Swiss networks (LTE "B", 5G NR "n")
    "B28 / n28": 700, "B20": 800, "B8": 900, "B32 / n75 (downlink only)": 1400,
    "B3 / n3": 1800, "B1 / n1": 2100, "B7": 2600, "n78": 3500,
}


def seed_from(matriculation) -> int:
    """A stable integer seed from a matriculation number such as '12-345-678'."""
    digits = re.sub(r"\D", "", str(matriculation))
    if len(digits) < 6:
        raise ValueError("Set MATRICULATION to your matriculation number, e.g. '12-345-678'.")
    return int(hashlib.sha256(digits.encode()).hexdigest()[:8], 16)


# ----------------------------------------------------------------------------- propagation
def o2i_loss_db(f_ghz):
    """Building entry loss, 3GPP TR 38.901 high-loss model (coated glass and concrete), median."""
    return 5 - 10 * np.log10(0.7 * 10 ** (-(23 + 0.3 * f_ghz) / 10) + 0.3 * 10 ** (-(5 + 4 * f_ghz) / 10))


def pl_uma_db(d_m, f_ghz):
    """Urban macro path loss, 3GPP TR 38.901 UMa NLOS (simplified, phone at 1.5 m)."""
    return 13.54 + 39.08 * np.log10(np.maximum(d_m, 35.0)) + 20 * np.log10(f_ghz)


def r_uma_m(pl_db, f_ghz):
    """Inverse of pl_uma_db: the distance at which the path loss reaches pl_db."""
    return 10 ** ((pl_db - 13.54 - 20 * np.log10(f_ghz)) / 39.08)


def pl_free_space_db(d_m, f_ghz):
    return 20 * np.log10(d_m) + 20 * np.log10(f_ghz * 1e9) - 147.55


def radio_horizon_km(h_mast_m, h_phone_m=1.5):
    """Line of sight over a smooth Earth, including standard refraction (4/3 Earth radius)."""
    return 4.12 * (np.sqrt(h_mast_m) + np.sqrt(h_phone_m))


def noise_dbm(bandwidth_hz, nf_db):
    return -174 + 10 * np.log10(bandwidth_hz) + nf_db


# ----------------------------------------------------------------------------- NISV
def nisv_erp_cap_w(d_flat_m, bands="both", k_aa=1.0, share=1.0):
    """Highest ERP per band (W) a site may radiate under the NISV installation limit.

    E = 7 * sqrt(ERP) / d  must stay below the limit at the nearest place of sensitive use
    (a flat, an office, a classroom) at distance d_flat_m. The vertical pattern attenuates
    the field there by VERTICAL_ATT_DB. Two bands on one installation share the budget.
    k_aa < 1 lets an adaptive antenna with automatic power control radiate up to 1/k_aa
    times more in its beam, as long as its 6-minute average stays below the permitted ERP.
    """
    e_lim = E_LIMIT_VM[bands]
    total = (e_lim * d_flat_m / 7.0) ** 2 * 10 ** (VERTICAL_ATT_DB / 10) * share
    per_band = total / (2 if bands == "both" else 1)
    return per_band / k_aa


def erp_w_to_eirp_dbm(erp_w):
    return 10 * np.log10(erp_w * 1e3) + 2.15


# ----------------------------------------------------------------------------- one cell
def link_budget(f_mhz, beamforming=True, d_flat_m=None, adaptive=True):
    """Maximum allowed path loss (MAPL) downlink and uplink, and the resulting cell radius.

    d_flat_m: distance from the antenna to the nearest flat; if given, the NISV cap may reduce the
    downlink power. adaptive: whether the 3.5 GHz antenna may use the K_AA correction factor.
    """
    b = BANDS[f_mhz]
    bf_dl = b["bf_dl"] if beamforming else 0.0
    bf_ul = b["bf_ul"] if beamforming else 0.0
    eirp_dl = P_BS_DBM + G_BS_DBI - FEEDER_DB + bf_dl
    capped_by = 0.0
    if d_flat_m is not None:
        k = K_AA if (adaptive and beamforming and f_mhz == 3500) else 1.0
        cap = erp_w_to_eirp_dbm(nisv_erp_cap_w(d_flat_m, "both", k_aa=k))
        capped_by = max(0.0, eirp_dl - cap)
        eirp_dl -= capped_by
    dl = eirp_dl - noise_dbm(b["b_dl"], NF_UE_DB) - SNR_MIN_DB
    ul = (P_UE_DBM + G_BS_DBI - FEEDER_DB + bf_ul) - noise_dbm(B_UL_EDGE_HZ, NF_BS_DB) - SNR_MIN_DB - b["tdd_ul"]
    mapl = min(dl, ul)
    o2i = float(o2i_loss_db(b["f_ghz"]))
    return dict(band=b["name"], beamforming=beamforming, eirp_dl_dbm=eirp_dl, nisv_cut_db=capped_by,
                mapl_dl_db=dl, mapl_ul_db=ul, limited_by="uplink" if ul < dl else "downlink",
                o2i_db=o2i, r_outdoor_m=float(r_uma_m(mapl, b["f_ghz"])), r_indoor_m=float(r_uma_m(mapl - o2i, b["f_ghz"])))


def print_link_budget(rows):
    print(f"{'band':22s}{'beamf.':>7s}{'EIRP':>7s}{'NISV cut':>10s}{'MAPL DL':>9s}{'MAPL UL':>9s}{'limit':>10s}"
          f"{'O2I':>6s}{'r outdoor':>11s}{'r indoor':>10s}")
    for r in rows:
        print(f"{r['band']:22s}{'yes' if r['beamforming'] else 'no':>7s}{r['eirp_dl_dbm']:7.0f}"
              f"{r['nisv_cut_db']:10.1f}{r['mapl_dl_db']:9.0f}{r['mapl_ul_db']:9.0f}{r['limited_by']:>10s}"
              f"{r['o2i_db']:6.1f}{r['r_outdoor_m']:9.0f} m{r['r_indoor_m']:8.0f} m")
    print("(EIRP in dBm; NISV cut: dB the downlink loses to the NISV cap; MAPL and O2I in dB)")


def coverage_radius_free_space_m(tx_dbm=P_UE_DBM, rx_sens_dbm=-90.0, gain_dbi=3.0, f_ghz=0.7):
    """A free-space model with 23 dBm and a -90 dBm sensitivity, to show why free space misleads in a city."""
    return float(10 ** ((tx_dbm + 2 * gain_dbi - rx_sens_dbm - 20 * np.log10(f_ghz * 1e9) + 147.55) / 20))


# ----------------------------------------------------------------------------- many cells
def _hex_sites(isd_m, rings):
    q, r = np.meshgrid(np.arange(-rings, rings + 1), np.arange(-rings, rings + 1))
    q, r = q.ravel(), r.ravel()
    xy = np.c_[isd_m * (q + r / 2), isd_m * r * np.sqrt(3) / 2]
    keep = np.hypot(*xy.T) <= rings * isd_m * 0.9
    return xy[keep], q[keep], r[keep]


def median_sinr(isd_m, f_mhz=3500, power_offset_db=0.0, reuse=1, users=2500, shadowing_db=7.0, seed=1):
    """Median downlink SINR of indoor users in a hexagonal network of 3-sector sites.

    isd_m: inter-site distance. power_offset_db: change of every site's power (-10 = one tenth).
    reuse: 1 = every sector uses the whole band; 3 = the band is split in three, neighbours differ.
    Returns (median SINR dB, capacity per site b/s, area capacity b/s per km2).
    """
    b = BANDS[f_mhz]
    rng = np.random.default_rng(seed)
    xy, q, r = _hex_sites(isd_m, 4)
    colour = (q - r) % 3 if reuse == 3 else np.zeros(len(xy), int)
    ue = rng.uniform(-1, 1, (users, 2)) * isd_m * 1.2
    dx, dy = ue[:, None, 0] - xy[None, :, 0], ue[:, None, 1] - xy[None, :, 1]
    d = np.hypot(dx, dy)
    phi = np.degrees(np.arctan2(dx, dy))
    shadow = rng.normal(0, shadowing_db, d.shape)
    eirp = P_BS_DBM + G_BS_DBI - FEEDER_DB + b["bf_dl"] + power_offset_db
    rx = []
    for az in (0, 120, 240):                                   # 3 sectors, 3GPP horizontal pattern
        dphi = (phi - az + 180) % 360 - 180
        rx.append(eirp - pl_uma_db(d, b["f_ghz"]) - o2i_loss_db(b["f_ghz"]) - np.minimum(12 * (dphi / 65) ** 2, 20) + shadow)
    rx = np.stack(rx, -1).reshape(users, -1)
    col3 = np.repeat(colour, 3)
    mw = 10 ** (rx / 10)
    best = mw.argmax(1)
    s = mw[np.arange(users), best]
    i = (mw * (col3[None, :] == col3[best][:, None])).sum(1) - s
    n = 10 ** (noise_dbm(b["b_eff"] / reuse, NF_UE_DB) / 10)
    sinr = 10 * np.log10(s / (i + n))
    se = np.where(sinr < -6.5, 0, np.minimum(0.75 * np.log2(1 + 10 ** (sinr / 10)), 5.5))   # b/s/Hz, capped
    site_cap = 3 * b["b_eff"] / reuse * se.mean()
    return float(np.median(sinr)), float(site_cap), float(site_cap / (isd_m ** 2 * np.sqrt(3) / 2 / 1e6))


def plot_sinr_vs_spacing(isd_list=(3000, 2000, 1200, 800, 500, 300, 200), f_mhz=3500, power_offsets_db=(0, -10)):
    """Median SINR against site spacing, one curve per power level. Returns the values."""
    isd_list = list(isd_list)
    out = {}
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for off, style in zip(power_offsets_db, ("-o", "--s", ":^", "-.d")):
        med = [median_sinr(isd, f_mhz, off)[0] for isd in isd_list]
        out[off] = med
        label = "full power" if off == 0 else f"{off:+.0f} dB ({10 ** (off / 10):g} of the power)"
        ax.semilogx(isd_list, med, style, label=label)
    ax.invert_xaxis()                                          # denser networks to the right
    ax.set_xticks(isd_list)
    ax.set_xticklabels([f"{v:,}" for v in isd_list])
    ax.minorticks_off()
    ax.set_xlabel("distance between sites (m), denser to the right")
    ax.set_ylabel("median SINR of indoor users (dB)")
    ax.set_title(f"{BANDS[f_mhz]['name']}: SINR against site spacing")
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.show()
    return dict(isd_m=isd_list, median_sinr_db=out)


def compare_reuse(isd_m=500, f_mhz=3500):
    """Reuse 1 against reuse 3 at one site spacing: median SINR and area capacity."""
    rows = {k: median_sinr(isd_m, f_mhz, reuse=k) for k in (1, 3)}
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    names = ["reuse 1", "reuse 3"]
    ax[0].bar(names, [rows[1][0], rows[3][0]], color=["tab:blue", "tab:orange"])
    ax[0].set_ylabel("median SINR (dB)")
    ax[1].bar(names, [rows[1][2] / 1e9, rows[3][2] / 1e9], color=["tab:blue", "tab:orange"])
    ax[1].set_ylabel("area capacity (Gb/s per km²)")
    for a, vals in zip(ax, ([rows[1][0], rows[3][0]], [rows[1][2] / 1e9, rows[3][2] / 1e9])):
        for x, v in enumerate(vals):
            a.text(x, v, f"{v:.2f}", ha="center", va="bottom")
        a.grid(alpha=0.3, axis="y")
    fig.suptitle(f"{BANDS[f_mhz]['name']}, sites {isd_m} m apart")
    plt.tight_layout()
    plt.show()
    for k in (1, 3):
        print(f"reuse {k}: median SINR {rows[k][0]:5.1f} dB, capacity per site {rows[k][1] / 1e6:5.0f} Mb/s, "
              f"area capacity {rows[k][2] / 1e9:4.2f} Gb/s per km²")
    return rows


# ----------------------------------------------------------------------------- planning: the knee
def sites_per_km2_for_radius(r_m):
    """Hexagonal 3-sector sites: each site covers about 2.6 r^2 (r = cell radius)."""
    return 1 / (2.6 * (r_m / 1e3) ** 2)


def knee_curves(per_sub_mbps=PER_SUB_MBPS):
    """Sites per km2 needed against subscribers per km2, per band, and where each band's knee is."""
    users = np.logspace(-2, 5, 141)
    demand = users * per_sub_mbps * 1e6                       # b/s per km2
    lb7 = link_budget(700)
    lb35 = link_budget(3500)
    cap = {}
    for f, lb in ((700, lb7), (3500, lb35)):
        isd = 2 * lb["r_indoor_m"] * 0.75                      # capacity measured at the coverage-limited spacing
        cap[f] = median_sinr(isd, f)[1]
    mapl7 = min(lb7["mapl_dl_db"], lb7["mapl_ul_db"])
    d = np.linspace(100, 40e3, 40000)
    r_rural = min(d[np.argmax(_pl_rma_db(d, 0.7) > mapl7)], radio_horizon_km(MAST_M) * 1e3)
    cov7, cov35, cov_r = (sites_per_km2_for_radius(lb7["r_indoor_m"]), sites_per_km2_for_radius(lb35["r_indoor_m"]),
                          sites_per_km2_for_radius(r_rural))
    s7 = np.maximum(cov7, demand / cap[700])
    s35 = np.maximum(cov35, demand / cap[3500])
    s7r = np.maximum(cov_r, demand / cap[700])
    knee = lambda cov, c: float(users[np.argmax(demand / c > cov)])
    return dict(users=users, demand_mbps=demand / 1e6, sites_700=s7, sites_3500=s35, sites_700_rural=s7r,
                cap_site_mbps={k: v / 1e6 for k, v in cap.items()}, coverage_floor={700: cov7, 3500: cov35, "rural": cov_r},
                knee={700: knee(cov7, cap[700]), 3500: knee(cov35, cap[3500]), "rural": knee(cov_r, cap[700])},
                r_rural_km=r_rural / 1e3, per_sub_mbps=per_sub_mbps)


def _pl_rma_db(d, f_ghz, hbs=MAST_M, hut=1.5, w=20, h=5):
    """Rural macro path loss, 3GPP TR 38.901 RMa NLOS (specified to 5 km, extrapolated beyond)."""
    d3 = np.hypot(d, hbs - hut)
    return (161.04 - 7.1 * np.log10(w) + 7.5 * np.log10(h) - (24.37 - 3.7 * (h / hbs) ** 2) * np.log10(hbs)
            + (43.42 - 3.1 * np.log10(hbs)) * (np.log10(d3) - 3) + 20 * np.log10(f_ghz) - (3.2 * np.log10(11.75 * hut) ** 2 - 4.97))


def plot_knee(densities=None, my_sites_per_km2=None, real_sites_per_km2=None):
    """The knee plot. densities: {label: subscribers per km2}, drawn as vertical lines.
    my_sites_per_km2: your estimate from the tram ride; real_sites_per_km2: from the board's real sites."""
    k = knee_curves()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.loglog(k["users"], k["sites_700"], color="tab:blue", lw=2, label="700 MHz, indoor phones")
    ax.loglog(k["users"], k["sites_3500"], color="tab:red", lw=2, label="3.5 GHz, indoor phones")
    ax.loglog(k["users"], k["sites_700_rural"], color="tab:green", lw=1.5, ls="--",
              label=f"700 MHz, rural, outdoor phones ({MAST_M:.0f} m masts)")
    for f, col in ((700, "tab:blue"), (3500, "tab:red")):
        ax.axvline(k["knee"][f], color=col, ls=":", lw=1)
        ax.text(k["knee"][f] * 1.1, 1.5e-3, f"knee\n{k['knee'][f]:,.0f}", color=col, fontsize=8)
    for i, (label, v) in enumerate((densities or {}).items()):
        ax.axvline(v, color="0.3", lw=1.2, ls="--")
        ax.text(v * 1.05, 200 / 3 ** i, label, fontsize=8, color="0.2")
    for v, label, m in ((my_sites_per_km2, "your tram-ride estimate", "*"), (real_sites_per_km2, "real sites (board)", "D")):
        if v:
            ax.axhline(v, color="purple", lw=1, ls="-.")
            ax.text(0.012, v * 1.15, label, color="purple", fontsize=8)
    ax.set_xlabel(f"subscribers of one operator per km² (busy hour, {k['per_sub_mbps']} Mb/s each)")
    ax.set_ylabel("sites per km²")
    ax.set_ylim(1e-3, 1e3)
    ax.set_title("Coverage-limited (flat) and capacity-limited (rising)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, loc="upper left")
    plt.tight_layout()
    plt.show()
    print(f"capacity per 3-sector site: 700 MHz {k['cap_site_mbps'][700]:.0f} Mb/s, 3.5 GHz {k['cap_site_mbps'][3500]:.0f} Mb/s")
    print(f"knees: 700 MHz {k['knee'][700]:,.0f}, 3.5 GHz {k['knee'][3500]:,.0f}, "
          f"rural 700 MHz {k['knee']['rural']:,.1f} subscribers per km²")
    return k


# ----------------------------------------------------------------------------- a first look: Zurich
def draw_zurich_grid(subscribers, rate_bps, f_mhz, gauss_strength=0.0, area_km2=88.0, grid_extent_m=3000,
                     city_diameter_m=5000, background="../../Admin/picture/zurich_map.jpg"):
    """A regular grid of 3-sector sites over central Zurich. The site spacing is set by coverage
    (the indoor radius of link_budget) or by capacity (demand per site), whichever is smaller.
    gauss_strength > 0 concentrates the users in the centre; sites that cannot carry their local
    demand are drawn red."""
    from matplotlib.patches import RegularPolygon, Circle
    import matplotlib.image as mpimg
    lb = link_budget(f_mhz)
    r_cov = lb["r_indoor_m"]
    cap_site = knee_curves()["cap_site_mbps"][f_mhz] * 1e6
    density = subscribers / area_km2
    r_cap = np.sqrt(cap_site / (density * rate_bps) / 2.6) * 1e3
    r = min(r_cov, r_cap)
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    try:
        ax.imshow(mpimg.imread(background), extent=[-grid_extent_m, grid_extent_m, -grid_extent_m, grid_extent_m],
                  origin="upper", alpha=0.8, zorder=0)
    except Exception as e:
        print(f"[note] map not loaded: {e}")
    city_r = city_diameter_m / 2
    sigma = city_r / 3
    g_avg = 2 * np.pi * sigma ** 2 * (1 - np.exp(-city_r ** 2 / (2 * sigma ** 2))) / (np.pi * city_r ** 2)
    dx, dy = 1.5 * r, np.sqrt(3) * r
    n_sites = n_over = 0
    for i in range(-int(grid_extent_m / dx) - 2, int(grid_extent_m / dx) + 3):
        for j in range(-int(grid_extent_m / dy) - 2, int(grid_extent_m / dy) + 3):
            x, y = i * dx, j * dy + (i % 2) * dy / 2
            if x * x + y * y > city_r ** 2:
                continue
            m = (1 - gauss_strength) + gauss_strength * np.exp(-(x * x + y * y) / (2 * sigma ** 2)) / g_avg
            over = r_cap / np.sqrt(m) < 0.999 * r
            colour = "red" if over else ("tab:green" if r_cap < r_cov else "tab:blue")
            ax.add_patch(RegularPolygon((x, y), 6, radius=r, orientation=np.radians(30), facecolor=colour,
                                        alpha=0.4, edgecolor="black", lw=0.5, zorder=2))
            n_sites += 1
            n_over += over
    ax.add_patch(Circle((0, 0), city_r, fill=False, color="white", lw=2, zorder=3))
    ax.set_xlim(-grid_extent_m, grid_extent_m)
    ax.set_ylim(-grid_extent_m, grid_extent_m)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(f"Zurich, {BANDS[f_mhz]['name']}: blue = coverage-limited, green = capacity-limited, "
                 f"red = overloaded", fontsize=9)
    plt.tight_layout()
    plt.show()
    print("Network summary")
    print(f"  subscribers {subscribers:,.0f} on {area_km2:.0f} km2 = {density:,.0f} per km2, {rate_bps / 1e6:.2f} Mb/s each")
    print(f"  coverage radius (indoor, {lb['limited_by']}-limited): {r_cov:,.0f} m")
    print(f"  capacity radius ({cap_site / 1e6:.0f} Mb/s per site): {r_cap:,.0f} m")
    print(f"  cell radius used: {r:,.0f} m -> {'capacity' if r_cap < r_cov else 'coverage'}-limited")
    print(f"  sites inside the circle: {n_sites} ({n_over} overloaded with gauss_strength = {gauss_strength})")


# ----------------------------------------------------------------------------- your phone
def eirp_per_re_dbm(p_tx_dbm=P_BS_DBM, gain_dbi=G_BS_DBI, loss_db=FEEDER_DB, bw_mhz=20, scs_khz=15, bf_db=0.0):
    """EIRP per resource element: RSRP is measured on one subcarrier, so the total power is
    spread over all subcarriers of the channel (about 90 % of the bandwidth carries them)."""
    n_sc = bw_mhz * 1e3 / scs_khz * 0.9
    return p_tx_dbm + gain_dbi - loss_db + bf_db - 10 * np.log10(n_sc)


def path_loss_from_rsrp(rsrp_dbm, bw_mhz=20, scs_khz=15, bf_db=0.0):
    """Path loss implied by a measured RSRP, if the site transmits with the typical power above."""
    return float(eirp_per_re_dbm(bw_mhz=bw_mhz, scs_khz=scs_khz, bf_db=bf_db) - rsrp_dbm)


def uma_distance_m(pl_db, f_mhz):
    """Distance at which 3GPP UMa NLOS reaches this path loss (outdoor phone)."""
    return float(r_uma_m(pl_db, f_mhz / 1e3))


def building_entry_loss(rsrp_outdoor_dbm, rsrp_indoor_dbm):
    """Only meaningful if both readings come from the same cell (same PCI) on the same band."""
    return rsrp_outdoor_dbm - rsrp_indoor_dbm


def spacing_from_ride(route_km, serving_cell_changes):
    """Site spacing and density implied by the serving-cell changes (PCI changes) along a ride.

    Every PCI belongs to one sector. A 3-sector site splits into three cells of radius
    spacing/3, and a straight route crosses such a cell over about 0.45 x the site spacing
    on average (mean chord of a hexagon), so the site spacing is about 2.2 km per change.
    """
    per_change_km = route_km / max(serving_cell_changes, 1)
    site_spacing_km = per_change_km / 0.45
    return dict(km_per_change=per_change_km, site_spacing_km=site_spacing_km,
                sites_per_km2=1 / (np.sqrt(3) / 2 * site_spacing_km ** 2))
