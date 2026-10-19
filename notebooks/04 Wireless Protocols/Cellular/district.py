"""
district - plan a 4G/5G network for a real Swiss district, by clicking on a map or in Python.

    from Cellular.district import make_district, planning_board, evaluate_plan, show_plan, auto_plan, plot_designs

    reg   = make_district("12-345-678")           # your district, candidate sites and shadowing
    board = planning_board(reg)                   # click sites on and off, switch the hour and the limits
    board.plan_string                             # the plan, to keep and to paste into your answer
    res   = evaluate_plan(reg, plan_string)       # the numbers of a plan
    show_plan(reg, plan_string)                   # the map of a plan, for your answer
    plan  = auto_plan(reg, budget_chf=8e6)        # a greedy planner, to compare with your own designs
    plot_designs(reg, {"A": plan_a, "B": plan_b}) # cost against demand served

The board is clickable with matplotlib's interactive mode (`%matplotlib widget`, package ipympl).
Without it, the board is a picture with every candidate site numbered: pass the sites as a list,
planning_board(reg, plan=[3, 17, 42]), and run the cell again.

Each district is a real 5 x 5 km city centre on the 100 m hectare grid: residents, jobs and buildings
from the Federal Statistical Office, and the real antenna sites from OFCOM (districts.npz, built by
build_districts.py). Demand: 25 % market share, 0.2 Mb/s per subscriber in the busy hour.

The model, kept deliberately simple:
- Candidate sites: share an existing rooftop installation (cheap, but the incumbents already use about
  85 % of its NISV budget), build a new rooftop site, or add a small cell (<= 6 W ERP, exempt from the
  NISV installation limit). Prices are illustrative 5-year costs.
- Two layers: 700 MHz (passive sector antennas) and 3.5 GHz (adaptive antennas). A hectare uses 3.5 GHz
  if its SINR there is at least 0 dB, else 700 MHz if at least -6 dB, and only if the phone's uplink
  reaches the site (the same uplink limit as link_budget() in cellular_tools).
- Interference is weighted by how busy each sector is, and how busy it is depends on the demand it
  serves, so the evaluation iterates. An adaptive antenna points its beam at the user it serves; the
  others see it on average 7 dB weaker.
- NISV: E = 7 sqrt(ERP) / d at the nearest flat (d), with 6 dB vertical attenuation, 5 V/m for an
  installation with both bands. "nisv": adaptive antennas assessed as if they always beamed at the
  flat (before 2021). "nisv_kaa": with the correction factor K_AA = 0.10 the beam may be up to 10x
  stronger, but the 6-minute average power must stay below the permit, so a busy sector cannot use it.
  "icnirp": the international limits (10x the field, 100x the power), as in most EU countries.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.widgets import Button, CheckButtons, RadioButtons

from .cellular_tools import (seed_from, E_LIMIT_VM, K_AA, VERTICAL_ATT_DB, P_UE_DBM, G_BS_DBI, FEEDER_DB,
                             NF_BS_DB, SNR_MIN_DB, B_UL_EDGE_HZ, NF_UE_DB, BANDS as LINK_BANDS, noise_dbm,
                             MARKET_SHARE, PER_SUB_MBPS)

HERE = Path(__file__).parent
_DATA = np.load(HERE / "districts.npz")
DISTRICTS = [str(n) for n in _DATA["names"]]
W, RES = 50, 100.0
P = W * W
BAND_KEYS = ("700", "3500")
LAYER = {"700": dict(f=0.7, B=10e6, pen=10.0, min_sinr_db=-6.0),      # pen: mean building entry, indoor and outdoor users
         "3500": dict(f=3.5, B=75e6, pen=18.0, min_sinr_db=0.0)}
HW_PEAK_W = {"700": 800.0, "3500": 25000.0}      # hardware maximum ERP per sector (3.5 GHz: beam peak of a 64-element array)
SMALL_ERP_W = 6.0
SPREAD_DB = 7.0                                  # adaptive beam peak over its average in other directions
LIMITS = ("nisv", "nisv_kaa", "icnirp")
LIMIT_NAMES = {"nisv": "NISV, worst case (before 2021)", "nisv_kaa": "NISV with K_AA = 0.10",
               "icnirp": "ICNIRP limits (EU)"}
HOURS = {"day": "weekday 11:00", "evening": "evening 21:00"}
PRICE = dict(new=320e3, share=150e3, small=45e3, fibre=40e3, microwave=25e3)
KIND_NAMES = {"share": "share an existing rooftop", "new": "new rooftop site", "small": "small cell"}
OFF_DB, STEP_DB = 40.0, 0.5                      # path gains stored compactly as uint8: loss = OFF + STEP * q, q = 255 means none


def _ul_threshold_db(kind, band):
    """Highest path loss at which the phone's uplink still reaches this site (same model as link_budget)."""
    gain, feeder, bf = (5.0, 0.0, 0.0) if kind == "small" else (G_BS_DBI, FEEDER_DB, LINK_BANDS[int(band)]["bf_ul"])
    return (P_UE_DBM + gain - feeder + bf - noise_dbm(B_UL_EDGE_HZ, NF_BS_DB) - SNR_MIN_DB
            - LINK_BANDS[int(band)]["tdd_ul"])


def _permitted_w(kind, d_omen, limits):
    """ERP per band a site may radiate (W): the NISV installation limit, or the ICNIRP limits."""
    if kind == "small":
        return {"700": 0.0, "3500": SMALL_ERP_W}
    total = (E_LIMIT_VM["both"] * d_omen / 7.0) ** 2 * 10 ** (VERTICAL_ATT_DB / 10)
    if limits == "icnirp":
        total *= 100.0
    if kind == "share":
        total *= 0.15
    return {b: total / 2 for b in BAND_KEYS}


class District:
    """One student's district: candidate sites, path gains, demand. Built by make_district()."""

    def __init__(self, matriculation):
        self.matriculation = str(matriculation)
        self.seed = seed_from(matriculation)
        rng = np.random.RandomState(self.seed % (2 ** 32))
        self.index = self.seed % len(DISTRICTS)
        self.name = DISTRICTS[self.index]
        k = self.index
        pop, fte, bld = (_DATA[f"{k}_{x}"].ravel().astype(float) for x in ("pop", "fte", "bld"))
        self.origin = _DATA[f"{k}_origin"]
        self.real_sites = _DATA[f"{k}_inst_xy"]
        self.real_small = _DATA[f"{k}_small_xy"]
        self.persons = {"day": 0.3 * pop + 1.0 * fte, "evening": 1.0 * pop + 0.1 * fte}
        self.demand = {h: p * MARKET_SHARE * PER_SUB_MBPS * 1e6 for h, p in self.persons.items()}   # b/s per hectare
        yy, xx = np.mgrid[0:W, 0:W]
        px = np.c_[(xx.ravel() + 0.5) * RES, (yy.ravel() + 0.5) * RES]
        built = np.flatnonzero(bld >= 1)
        n_share = min(100, len(self.real_sites))
        share = self.real_sites[rng.choice(len(self.real_sites), n_share, replace=False)]
        new = px[rng.choice(built, 100, replace=False)] + rng.uniform(-30, 30, (100, 2))
        small = px[rng.choice(built, 60, replace=False)] + rng.uniform(-30, 30, (60, 2))
        self.cands = []
        for kind, xy in (("share", share), ("new", new), ("small", small)):
            for x, y in xy:
                cell = int(np.clip(y // RES, 0, W - 1)) * W + int(np.clip(x // RES, 0, W - 1))
                d_omen = float(np.clip((8 + 60 / np.sqrt(bld[cell] + 1)) * rng.uniform(0.7, 1.3), 10, 120))
                fibre = bool(bld[cell] >= 3)
                cost = PRICE[kind] + (PRICE["fibre"] if fibre else PRICE["microwave"])
                self.cands.append(dict(kind=kind, x=round(float(x), 1), y=round(float(y), 1), d_omen=round(d_omen, 1),
                                       fibre=fibre, cost=cost,
                                       permitted={lim: _permitted_w(kind, round(d_omen, 1), lim) for lim in ("nisv", "icnirp")}))
        # path gains (dB, without the ERP): macro 3GPP UMa NLOS + 3-sector pattern, small cell UMi NLOS omni,
        # mean building entry, 6 dB log-normal shadowing; stored in steps of 0.5 dB
        q = np.full((len(self.cands), 3, 2, P), 255, np.uint8)
        for c, cd in enumerate(self.cands):
            d = np.maximum(np.hypot(px[:, 0] - cd["x"], px[:, 1] - cd["y"]), 20.0)
            phi = np.degrees(np.arctan2(px[:, 0] - cd["x"], px[:, 1] - cd["y"]))
            sh = rng.normal(0, 6, P)
            for b, bk in enumerate(BAND_KEYS):
                f, pen = LAYER[bk]["f"], LAYER[bk]["pen"]
                if cd["kind"] == "small":
                    if bk == "3500":
                        q[c, 0, b] = self._quantise(-(22.4 + 35.3 * np.log10(d) + 21.3 * np.log10(f)) - pen + sh)
                    continue
                pl = 13.54 + 39.08 * np.log10(d) + 20 * np.log10(f)
                for s, az in enumerate((0, 120, 240)):
                    dphi = (phi - az + 180) % 360 - 180
                    q[c, s, b] = self._quantise(-pl - np.minimum(12 * (dphi / 65) ** 2, 20) - pen + sh)
        self.q = q
        self.ul_thr = {kind: {b: _ul_threshold_db(kind, b) for b in BAND_KEYS} for kind in ("share", "new", "small")}

    @staticmethod
    def _quantise(g_db):
        return np.clip(np.round((-g_db - OFF_DB) / STEP_DB), 0, 255).astype(np.uint8)

    def gain_db(self, c, s, b):
        qq = self.q[c, s, b].astype(float)
        return np.where(qq >= 255, -np.inf, -(OFF_DB + STEP_DB * qq))

    def __repr__(self):
        e0, n0 = self.origin
        return (f"District {self.name} (5 x 5 km, lower-left corner E {e0}, N {n0} in Swiss coordinates), "
                f"{len(self.cands)} candidate sites, {len(self.real_sites)} real macro installations")


def make_district(matriculation):
    """Your district, its candidate sites and its radio environment, from your matriculation number."""
    return District(matriculation)


def density_summary(reg):
    """Subscribers of one operator per km2 in the district: averages and the busiest hectares."""
    out = {}
    for h, label in HOURS.items():
        subs = reg.persons[h] * MARKET_SHARE * 100                       # per hectare -> per km2
        out[f"{label}, average"] = float(subs.mean())
        out[f"{label}, busiest 1 %"] = float(np.percentile(subs, 99))
    real = len(reg.real_sites) / (W * RES / 1e3) ** 2
    print(f"{reg.name}: subscribers of one operator per km2 ({MARKET_SHARE:.0%} market share)")
    for k, v in out.items():
        print(f"   {k:28s}{v:10,.0f}")
    print(f"   real macro installations (all operators): {len(reg.real_sites)}, {real:.1f} per km2")
    return out, real


# ----------------------------------------------------------------------------- evaluation
def _parse(reg, plan):
    if isinstance(plan, str):
        d = json.loads(plan)
        if re.sub(r"\D", "", str(d.get("matriculation", ""))) != re.sub(r"\D", "", reg.matriculation):
            raise ValueError("This plan was made on another student's board.")
        return [int(c) for c in d["plan"]], d.get("hour", "evening"), d.get("limits", "nisv")
    if isinstance(plan, dict):
        return [int(c) for c in plan["plan"]], plan.get("hour", "evening"), plan.get("limits", "nisv")
    return [int(c) for c in plan], None, None


def evaluate(reg, plan, hour="evening", limits="nisv", detail=False, iters=6):
    """Evaluate a plan (list of candidate numbers). At one hour, under one set of limits."""
    assert hour in HOURS and limits in LIMITS, (hour, limits)
    plan = sorted(set(int(c) for c in plan))
    D = reg.demand[hour]
    lim_key = "icnirp" if limits == "icnirp" else "nisv"
    layers = {}
    for b, bk in enumerate(BAND_KEYS):
        rows, owner = [], []
        for c in plan:
            cd = reg.cands[c]
            if cd["permitted"][lim_key][bk] <= 0:
                continue
            for s in range(1 if cd["kind"] == "small" else 3):
                rows.append((c, s))
                owner.append(c)
        if not rows:
            layers[bk] = None
            continue
        g = np.array([reg.gain_db(c, s, b) for c, s in rows])
        lin = np.where(np.isfinite(g), 10 ** (g / 10), 0.0)
        kinds = [reg.cands[c]["kind"] for c, _ in rows]
        perm = np.array([reg.cands[c]["permitted"][lim_key][bk] for c, _ in rows])
        hw = np.array([SMALL_ERP_W if k == "small" else HW_PEAK_W[bk] for k in kinds])
        adaptive = np.array([(k != "small") and bk == "3500" for k in kinds])
        spread = np.where(adaptive, 10 ** (-SPREAD_DB / 10), 1.0)
        thr = np.array([reg.ul_thr[k][bk] for k in kinds])
        ul_ok = (g >= -thr[:, None]).any(0)
        layers[bk] = dict(lin=lin, perm=perm, hw=hw, adaptive=adaptive, spread=spread, ul_ok=ul_ok,
                          owner=np.array(owner), load=np.ones(len(rows)))
    noise = {bk: 10 ** (noise_dbm(LAYER[bk]["B"], NF_UE_DB) / 10) for bk in BAND_KEYS}

    def erp_peak(L):
        if limits == "nisv_kaa":
            mult = np.where(L["adaptive"], 1 / np.maximum(K_AA, L["load"]), 1.0)
        else:
            mult = 1.0
        return np.minimum(L["hw"], L["perm"] * mult)

    def radio(bk):
        L = layers[bk]
        if L is None:
            z = np.zeros(P)
            return z, z, np.zeros(P, int)
        rx = (erp_peak(L) * 1e3 * 10 ** (2.15 / 10))[:, None] * L["lin"]              # mW
        best = rx.argmax(0)
        S = rx[best, np.arange(P)]
        w = (L["spread"] * L["load"])[:, None]
        I = (w * rx).sum(0) - w[best, 0] * S
        return S / (I + noise[bk]), S / noise[bk], best

    for it in range(iters):
        q = {bk: radio(bk) for bk in BAND_KEYS}
        use = {}
        use["3500"] = (q["3500"][0] >= 10 ** (LAYER["3500"]["min_sinr_db"] / 10)) & (
            layers["3500"]["ul_ok"] if layers["3500"] else False)
        use["700"] = ~use["3500"] & (q["700"][0] >= 10 ** (LAYER["700"]["min_sinr_db"] / 10)) & (
            layers["700"]["ul_ok"] if layers["700"] else False)
        served = np.zeros(P)
        airtime = {}
        for bk in ("3500", "700"):
            L = layers[bk]
            if L is None:
                continue
            sinr, _, best = q[bk]
            se = np.minimum(5.5, 0.75 * np.log2(1 + sinr))
            need = np.where(use[bk], D / (se * LAYER[bk]["B"] + 1e-9), 0.0)
            A = np.bincount(best[use[bk]], weights=need[use[bk]], minlength=len(L["load"]))
            frac = np.minimum(1, 1 / np.maximum(A, 1e-12))
            served += np.where(use[bk], D * frac[best], 0.0)
            new_load = np.clip(A, 0.05, 1.0)
            L["load"] = 0.5 * (L["load"] + new_load) if it else new_load
            airtime[bk] = A
    cov = use["3500"] | use["700"]
    # why an uncovered pixel is uncovered: it would be covered without interference -> interference-limited
    no_int = np.zeros(P, bool)
    for bk in BAND_KEYS:
        if layers[bk] is not None:
            no_int |= (q[bk][1] >= 10 ** (LAYER[bk]["min_sinr_db"] / 10)) & layers[bk]["ul_ok"]
    state = np.where(D <= 0, -1, np.where(cov, np.where(served >= 0.999 * D, 0, 1), np.where(no_int, 2, 3)))
    persons = reg.persons[hour]
    res = dict(district=reg.name, hour=hour, limits=limits, sites=len(plan),
               cost_chf=float(sum(reg.cands[c]["cost"] for c in plan)),
               served=float(served.sum() / D.sum()), covered_people=float((persons * cov).sum() / persons.sum()),
               demand_share={name: float(D[state == k].sum() / D.sum()) for k, name in
                             enumerate(("served", "capacity-limited", "interference-limited", "coverage-limited"))})
    if detail:
        res.update(state=state, served_px=served, sinr35=10 * np.log10(np.maximum(q["3500"][0], 1e-12)),
                   sinr7=10 * np.log10(np.maximum(q["700"][0], 1e-12)), use35=use["3500"], use7=use["700"])
    return res


def evaluate_plan(reg, plan, hour=None, limits=None, quiet=False):
    """The numbers of a plan: a plan string from the board, or a list of site numbers."""
    sites, h, l = _parse(reg, plan)
    res = evaluate(reg, sites, hour or h or "evening", limits or l or "nisv")
    if not quiet:
        ds = res["demand_share"]
        print(f"{reg.name}, {HOURS[res['hour']]}, {LIMIT_NAMES[res['limits']]}: {res['sites']} sites, "
              f"CHF {res['cost_chf'] / 1e6:.2f} M, demand served {res['served'] * 100:.1f} %, "
              f"people covered {res['covered_people'] * 100:.1f} %")
        print(f"   demand that is capacity-limited {ds['capacity-limited'] * 100:.1f} %, interference-limited "
              f"{ds['interference-limited'] * 100:.1f} %, coverage-limited {ds['coverage-limited'] * 100:.1f} %")
    return res


def plan_string(reg, plan, hour="evening", limits="nisv"):
    return json.dumps(dict(matriculation=reg.matriculation, district=reg.name, hour=hour, limits=limits,
                           plan=sorted(set(int(c) for c in plan))))


STATE_COLOURS = ["#2ca02c", "#ff7f0e", "#9467bd", "#d62728"]
STATE_NAMES = ["served", "capacity-limited", "interference-limited", "coverage-limited"]


def show_plan(reg, plan, hour=None, limits=None, title=None, real_sites=False):
    """Map of a plan: what limits each hectare, and where the sites are."""
    sites, h, l = _parse(reg, plan)
    res = evaluate(reg, sites, hour or h or "evening", limits or l or "nisv", detail=True)
    st = res["state"].reshape(W, W).astype(float)
    st[st < 0] = np.nan
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    persons = reg.persons[res["hour"]].reshape(W, W)
    ax.imshow(np.log10(1 + persons), origin="lower", extent=[0, 5, 0, 5], cmap="Greys", alpha=0.6)
    ax.imshow(st, origin="lower", extent=[0, 5, 0, 5], cmap=ListedColormap(STATE_COLOURS), vmin=-0.5, vmax=3.5, alpha=0.5)
    marker = {"share": "s", "new": "^", "small": "o"}
    for c in sites:
        cd = reg.cands[c]
        ax.plot(cd["x"] / 1e3, cd["y"] / 1e3, marker[cd["kind"]], color="#1f6feb", mec="white", ms=8)
    if real_sites:
        ax.plot(reg.real_sites[:, 0] / 1e3, reg.real_sites[:, 1] / 1e3, "k+", ms=5, label="real installations")
    for k, name in enumerate(STATE_NAMES):
        ax.plot([], [], "s", color=STATE_COLOURS[k], label=name)
    ax.legend(loc="upper right", fontsize=7, framealpha=0.85)
    ax.set_xlabel("km")
    ax.set_ylabel("km")
    ax.set_title(title or f"{reg.name}, {HOURS[res['hour']]}, {LIMIT_NAMES[res['limits']]}\n"
                 f"{res['sites']} sites, CHF {res['cost_chf'] / 1e6:.2f} M, served {res['served'] * 100:.1f} %", fontsize=10)
    plt.tight_layout()
    plt.show()
    return res


def auto_plan(reg, budget_chf=8e6, hour="evening", limits="nisv", kinds=("share", "new", "small"), verbose=True):
    """A simple automatic planner: repeatedly add the site with the most extra demand served per franc
    (lazy greedy), until the budget is spent. Returns a plan string for the board."""
    cost = lambda c: reg.cands[c]["cost"]
    plan, cur, spent = [], 0.0, 0.0
    bound = {c: np.inf for c, cd in enumerate(reg.cands) if cd["kind"] in kinds}
    while True:
        bound = {c: v for c, v in bound.items() if spent + cost(c) <= budget_chf}
        if not bound:
            break
        while True:                         # lazy greedy: re-evaluate the top candidate until it stays on top
            c = max(bound, key=bound.get)
            gain = evaluate(reg, plan + [c], hour, limits)["served"] - cur
            bound[c] = gain / cost(c)
            if bound[c] >= max((v for k, v in bound.items() if k != c), default=-np.inf):
                break
        if bound[c] <= 0:
            break
        plan.append(c)
        spent += cost(c)
        cur += gain
        del bound[c]
    s = plan_string(reg, plan, hour, limits)
    if verbose:
        print(f"auto_plan: {len(plan)} sites, CHF {spent / 1e6:.2f} M, served {cur * 100:.1f} %")
    return s


def plot_designs(reg, designs):
    """Cost against demand served for several designs: {label: plan string}. Mark the dominated ones yourself."""
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    rows = []
    for label, plan in designs.items():
        r = evaluate_plan(reg, plan, quiet=True)
        rows.append((label, r))
        ax.scatter(r["cost_chf"] / 1e6, r["served"] * 100, s=50)
        ax.annotate(f"{label}\n{HOURS[r['hour']].split()[0]}, {r['limits']}", (r["cost_chf"] / 1e6, r["served"] * 100),
                    textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax.set_xlabel("5-year cost (CHF million, illustrative)")
    ax.set_ylabel("busy-hour demand served (%)")
    ax.set_title(f"{reg.name}: your designs")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.show()
    print(f"{'design':12s}{'hour':>9s}{'limits':>10s}{'sites':>7s}{'CHF M':>8s}{'served':>9s}{'covered':>9s}")
    for label, r in rows:
        print(f"{label:12s}{r['hour']:>9s}{r['limits']:>10s}{r['sites']:7d}{r['cost_chf'] / 1e6:8.2f}"
              f"{r['served'] * 100:8.1f}%{r['covered_people'] * 100:8.1f}%")
    return rows


# ----------------------------------------------------------------------------- the planning board
def clickable_plots():
    """Switch this notebook to clickable figures (matplotlib's widget mode, package ipympl).
    Returns True if that worked; otherwise figures stay pictures and the board takes a list of sites."""
    try:
        from IPython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")
        return _is_interactive()
    except Exception as e:
        print(f"[note] clickable figures are not available here ({type(e).__name__}). The board is drawn as a "
              "picture with numbered sites: pass your sites as planning_board(reg, plan=[...]).")
        return False


def _is_interactive():
    b = matplotlib.get_backend().lower()
    return any(k in b for k in ("ipympl", "widget", "nbagg", "qt", "tk", "macosx", "gtk", "wx"))


LIMIT_BUTTONS = ["NISV, worst case", "NISV with K_AA", "ICNIRP (EU)"]


class PlanningBoard:
    """The district on a map. Clickable in widget mode: click a candidate site to add or remove it,
    click a hectare to see why it is (not) served, and switch the hour and the limits on the right."""

    MARKERS = {"share": "s", "new": "^", "small": "o"}
    SIZES = {"share": 34, "new": 46, "small": 22}

    def __init__(self, reg, plan=(), hour="evening", limits="nisv", labels=None):
        assert hour in HOURS and limits in LIMITS, (hour, limits)
        self.reg, self.hour, self.limits = reg, hour, limits
        self.plan = set(int(c) for c in plan)
        self.interactive = _is_interactive()
        self.labels = (not self.interactive) if labels is None else labels
        self.show_real = False
        self._hover = None
        self.xy = np.array([[c["x"], c["y"]] for c in reg.cands]) / 1e3          # km
        self._build()
        self._refresh()
        if not self.interactive:
            plt.show()

    @property
    def plan_string(self):
        """The plan as a string: keep it in a variable, and paste it into your answer."""
        return plan_string(self.reg, self.plan, self.hour, self.limits)

    def set_plan(self, plan):
        """Replace the plan by a list of site numbers (or a plan string) and redraw."""
        self.plan = set(_parse(self.reg, plan)[0])
        self._refresh()

    # --- drawing
    def _build(self):
        reg = self.reg
        self.fig = fig = plt.figure(figsize=(11.5, 7.4) if self.labels else (10.5, 6.6))
        if hasattr(fig.canvas, "header_visible"):           # ipympl: no "Figure 1" title bar
            fig.canvas.header_visible = False
        self.ax = ax = fig.add_axes([0.045, 0.07, 0.56, 0.88])
        self.bg = ax.imshow(self._persons_img(), origin="lower", extent=[0, 5, 0, 5], cmap="Greys",
                            interpolation="nearest")
        self.overlay = ax.imshow(np.full((W, W), np.nan), origin="lower", extent=[0, 5, 0, 5],
                                 cmap=ListedColormap(STATE_COLOURS), vmin=-0.5, vmax=3.5, alpha=0.6,
                                 interpolation="nearest")
        self.real = ax.plot(reg.real_sites[:, 0] / 1e3, reg.real_sites[:, 1] / 1e3, "+", color="black", ms=5,
                            mew=1.0, visible=False, zorder=2)[0]
        self.idx, self.sc = {}, {}
        for kind, m in self.MARKERS.items():
            idx = np.array([c for c, cd in enumerate(reg.cands) if cd["kind"] == kind])
            self.idx[kind] = idx
            self.sc[kind] = ax.scatter(self.xy[idx, 0], self.xy[idx, 1], marker=m, s=self.SIZES[kind], zorder=3,
                                       facecolors="white", edgecolors="0.15", linewidths=0.8)
        if self.labels:
            for c, (x, y) in enumerate(self.xy):
                ax.text(x, y + 0.06, str(c), fontsize=5.5, ha="center", va="bottom", zorder=4, color="0.1")
        self.cursor = ax.scatter(np.empty(0), np.empty(0), s=170, facecolors="none", edgecolors="#1f6feb",
                                 linewidths=1.6, zorder=5)
        ax.set_xlim(0, 5)
        ax.set_ylim(0, 5)
        ax.set_xlabel("km")
        ax.set_ylabel("km")
        handles = [plt.Line2D([], [], ls="", marker="s", ms=8, color=STATE_COLOURS[k], alpha=0.7) for k in range(4)]
        handles += [plt.Line2D([], [], ls="", marker=self.MARKERS[k], ms=6, mfc="white", mec="0.15") for k in self.MARKERS]
        handles += [plt.Line2D([], [], ls="", marker="+", ms=6, color="black")]
        names = STATE_NAMES + ["share existing rooftop", "new rooftop site", "small cell (<= 6 W)", "real installation"]
        x0 = 0.645
        fig.legend(handles, names, loc="lower left", bbox_to_anchor=(x0 - 0.008, 0.01), ncol=2, fontsize=7.5,
                   frameon=False, columnspacing=1.2, handletextpad=0.3)
        self.title = fig.text(x0, 0.955, "", fontsize=11, weight="bold", va="top")
        self.stats = fig.text(x0, 0.905, "", fontsize=10, va="top", linespacing=1.55)
        self.bar = fig.add_axes([x0, 0.70, 0.33, 0.03])
        self.bar.set_axis_off()
        self.barlbl = fig.text(x0, 0.685, "", fontsize=7.5, va="top", linespacing=1.4)
        if self.interactive:
            fig.text(x0, 0.6, "hour", fontsize=8, color="0.35")
            fig.text(x0 + 0.155, 0.6, "limits", fontsize=8, color="0.35")
            self.r_hour = RadioButtons(fig.add_axes([x0, 0.49, 0.145, 0.1], frameon=False),
                                       list(HOURS.values()), active=list(HOURS).index(self.hour))
            self.r_lim = RadioButtons(fig.add_axes([x0 + 0.155, 0.46, 0.19, 0.13], frameon=False),
                                      LIMIT_BUTTONS, active=LIMITS.index(self.limits))
            self.c_real = CheckButtons(fig.add_axes([x0, 0.39, 0.2, 0.06], frameon=False), ["real installations"], [False])
            self.b_clear = Button(fig.add_axes([x0 + 0.23, 0.4, 0.09, 0.045]), "clear plan")
            for w in (self.r_hour, self.r_lim, self.c_real):
                for t in w.labels:
                    t.set_fontsize(8.5)
            self.r_hour.on_clicked(self._on_hour)
            self.r_lim.on_clicked(self._on_limits)
            self.c_real.on_clicked(self._on_real)
            self.b_clear.on_clicked(self._on_clear)
            fig.canvas.mpl_connect("button_press_event", self._on_click)
            fig.canvas.mpl_connect("motion_notify_event", self._on_move)
            hint = "Click a site to add or remove it.\nClick a hectare to see what limits it."
        else:
            hint = ("This board is a picture here. Set its sites with\n"
                    "planning_board(reg, plan=[...], hour=..., limits=...)\nand run the cell again.")
        self.info = fig.text(x0, 0.355, hint, fontsize=8.5, va="top", linespacing=1.5)

    def _persons_img(self):
        return np.log10(1 + self.reg.persons[self.hour]).reshape(W, W)

    def _refresh(self):
        reg = self.reg
        self.res = r = evaluate(reg, sorted(self.plan), self.hour, self.limits, detail=True)
        st = r["state"].astype(float)
        st[st < 0] = np.nan
        if not self.plan:
            st[:] = np.nan
        self.overlay.set_data(st.reshape(W, W))
        img = self._persons_img()
        self.bg.set_data(img)
        self.bg.set_clim(0, 1.8 * img.max())                 # light grey, so the colours stay readable on top
        for kind, idx in self.idx.items():
            on = np.array([c in self.plan for c in idx])
            self.sc[kind].set_facecolors(np.where(on[:, None], [0.12, 0.43, 0.92, 1.0], [1.0, 1.0, 1.0, 0.85]))
        self.real.set_visible(self.show_real)
        self.title.set_text(f"{reg.name}, matriculation number {reg.matriculation}")
        self.stats.set_text(f"demand served:  {r['served'] * 100:.1f} %\n"
                            f"people covered: {r['covered_people'] * 100:.1f} %\n"
                            f"{r['sites']} sites, CHF {r['cost_chf'] / 1e6:.2f} M (5 years)\n"
                            f"{HOURS[self.hour]}, {LIMIT_NAMES[self.limits]}")
        self.bar.clear()
        self.bar.set_axis_off()
        shares = [r["demand_share"][n] for n in STATE_NAMES]
        self.bar.barh(0, shares, left=np.cumsum([0] + shares[:-1]), color=STATE_COLOURS, alpha=0.8, height=1)
        self.bar.set_xlim(0, 1)
        pairs = [f"{n} {v * 100:.1f} %" for n, v in zip(STATE_NAMES, shares)]
        self.barlbl.set_text(f"share of the demand: {pairs[0]}, {pairs[1]},\n{pairs[2]}, {pairs[3]}")
        self.fig.canvas.draw_idle()

    # --- interaction
    def _nearest(self, x, y, within_km=0.09):
        d = np.hypot(self.xy[:, 0] - x, self.xy[:, 1] - y)
        c = int(np.argmin(d))
        return c if d[c] <= within_km else None

    def _busy(self):
        mode = getattr(getattr(self.fig.canvas, "toolbar", None), "mode", "")
        return bool(str(mode))                       # the zoom or pan tool is active

    def _on_click(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None or self._busy():
            return
        c = self._nearest(ev.xdata, ev.ydata)
        if c is not None:
            self.plan.symmetric_difference_update({c})
            self._refresh()
            self._show_site(c)
        else:
            self._show_hectare(int(ev.xdata * 10), int(ev.ydata * 10))

    def _on_move(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        c = self._nearest(ev.xdata, ev.ydata)
        if c != self._hover:
            self._hover = c
            if c is not None:
                self._show_site(c)

    def _show_site(self, c):
        cd = self.reg.cands[c]
        perm = cd["permitted"]["icnirp" if self.limits == "icnirp" else "nisv"]
        k = 1 / K_AA if self.limits == "nisv_kaa" else 1.0
        p35 = SMALL_ERP_W if cd["kind"] == "small" else min(HW_PEAK_W["3500"], perm["3500"] * k)
        p7 = "none" if cd["kind"] == "small" else f"{min(HW_PEAK_W['700'], perm['700']):.0f} W ERP per sector"
        idle = " (idle sector)" if self.limits == "nisv_kaa" and cd["kind"] != "small" else ""
        self.cursor.set_offsets(self.xy[[c]])
        self.info.set_text(f"Site {c}: {KIND_NAMES[cd['kind']]}{', in the plan' if c in self.plan else ''}\n"
                           f"nearest flat {cd['d_omen']:.0f} m\n"
                           f"700 MHz: {p7}\n"
                           f"3.5 GHz: beam up to {p35:.0f} W ERP{idle}\n"
                           f"cost CHF {cd['cost'] / 1e3:.0f}k, backhaul by {'fibre' if cd['fibre'] else 'microwave'}")
        self.fig.canvas.draw_idle()

    def _show_hectare(self, j, i):
        if not (0 <= i < W and 0 <= j < W):
            return
        p, r = i * W + j, self.res
        D = self.reg.demand[self.hour][p]
        state = "no demand" if r["state"][p] < 0 else STATE_NAMES[r["state"][p]]
        layer = "3.5 GHz" if r["use35"][p] else ("700 MHz" if r["use7"][p] else "none")
        sinr = (f"SINR 3.5 GHz {r['sinr35'][p]:.1f} dB, 700 MHz {r['sinr7'][p]:.1f} dB" if self.plan else "no sites yet")
        served = r["served_px"][p] / D * 100 if D > 0 else 0.0
        self.cursor.set_offsets([[(j + 0.5) / 10, (i + 0.5) / 10]])
        self.info.set_text(f"Hectare ({j}, {i}): {state}\n"
                           f"{self.reg.persons[self.hour][p]:.0f} people, demand {D / 1e6:.2f} Mb/s\n"
                           f"served {served:.0f} %, layer used: {layer}\n{sinr}")
        self.fig.canvas.draw_idle()

    def _on_hour(self, label):
        self.hour = [h for h, n in HOURS.items() if n == label][0]
        self._refresh()

    def _on_limits(self, label):
        self.limits = LIMITS[LIMIT_BUTTONS.index(label)]
        self._refresh()

    def _on_real(self, label):
        self.show_real = not self.show_real
        self._refresh()

    def _on_clear(self, event):
        self.plan.clear()
        self._refresh()


def planning_board(reg, plan=(), hour="evening", limits="nisv", labels=None):
    """The district's planning board. plan: site numbers or a plan string to start from.
    labels: write every site's number on the map (default: only when the board is not clickable)."""
    if isinstance(plan, (str, dict)):
        plan, h, l = _parse(reg, plan)
        hour, limits = h or hour, l or limits
    return PlanningBoard(reg, plan, hour, limits, labels)
