"""GTA VI trophy rarity forecaster (make.fun: gta6-trophy-rarity-forecast-01).

The program reads one case file per run from the input directory and writes,
for every trophy in the case, five quantiles (5%, 25%, 50%, 75%, 95%) of the
trophy's earn rate on Exophase at the case's target time. The earn rate is a
ratio, so the forecast is built as a ratio too:

    earn rate = earners / players_tracked

where `earners` is the (implied) number of tracked players who hold the
trophy and `players_tracked` is the size of Exophase's tracked pool. The two
parts move for different reasons and are forecast separately:

* The tracked pool grows as Exophase ingests more players. Early growth is
  explosive (the pool multiplied by six at the first refresh after launch)
  and then decelerates, so the pool is extrapolated with a power law in
  time blended with a damped version of its recent growth rate.
* Earners of a trophy are a cumulative count: they never decrease. They
  grow as the existing cohort progresses through the game and as newcomers
  reach the trophy, which is again close to a power law in time since
  launch for the first week. Each trophy's earners are extrapolated with
  their own shrunk power-law fit, blended with their recent growth, and
  floored at the last observed count.

Exophase only republishes its counts at discrete refreshes, so the page a
case's history shows is a step function: long flat stretches (one refresh
state repeated) separated by jumps. Only the distinct refresh states carry
information about the trend, so all fits run on the deduplicated states,
never on the raw reads.

When the history holds a single refresh state (the launch-night practice
cases are like this: the first refresh has not happened yet), no trend can
be estimated at all. The forecaster then falls back on a launch prior: the
tracked pool is expected to multiply as the launch influx is ingested,
earners grow much more slowly than the pool, so most rates are diluted
down, and the predictive spread is made very wide to price the unseen
refresh.

Per-trophy growth fits are noisy when a trophy is held by a handful of
players, so the earner forecasts are partially pooled: each trophy's
growth factor is shrunk toward the median growth factor across trophies,
weighted by how many earners back its fit. The median's move from the
last observed rate is capped at 4.5 logit units.

The predictive distribution for each trophy is logistic-normal: quantiles
are taken on the logit scale around the forecast median, with a spread
that grows with the square root of the horizon (a random walk's scaling),
blended with the volatility the case's own refreshes actually showed,
plus a refresh-uncertainty term, plus extra width for trophies held by
only a handful of players, whose rates are dominated by counting noise.

Standard library only. Deterministic: the output is a pure function of the
case file. No network, no clock, no randomness.

Run locally the same way the grader does, with the kit's practice input:
    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader runs `python3 -P -s /bot/main.py`, which leaves this file's
# directory off sys.path; put it back first so sibling modules would import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in output order.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (more digits than the
# starter's, so the five points sit exactly on one logistic-normal curve).
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

# Spread of a rate's move on the logit scale, per square-root day, before
# refresh uncertainty is added. The house baseline uses 0.5; a launch week
# with discrete Exophase refreshes moves more than a smooth random walk.
BASE_SIGMA = 0.55
# Extra logit spread (total, not per day) allowed for the timing and size
# of the next Exophase refresh when refreshes have been observed, and the
# much larger allowance when none has been observed yet.
REFRESH_SIGMA_SEEN = 0.30
REFRESH_SIGMA_UNSEEN = 1.05
# Hard cap on the total predictive spread, in logit units.
SIGMA_CAP = 2.9
# The largest move, in logit units, the median may make from the last
# observed rate. Week one moves rates a lot (a chapter trophy can go from
# 1% to tens of percent as the cohort progresses), but an unbounded fit
# can also run away; 4.5 logit units is roughly a 90-fold odds move.
MAX_MEDIAN_MOVE = 4.5


def parse_time(text):
    """Parse an ISO 8601 timestamp to epoch seconds (float)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def clamp_rate(pct):
    """Clamp a percent into the range where its logit is finite."""
    return min(99.99, max(0.01, pct))


def logit(pct):
    p = clamp_rate(pct) / 100.0
    return math.log(p / (1.0 - p))


def logistic(value):
    if value >= 0:
        return 100.0 / (1.0 + math.exp(-value))
    exp_v = math.exp(value)
    return 100.0 * exp_v / (1.0 + exp_v)


def round4(x):
    """Round to 4 decimals, half up, writing whole numbers as ints."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if float(value).is_integer() else value


def wls_line(xs, ys, ws):
    """Weighted least squares fit of y = a + b*x. Returns (a, b)."""
    sw = sum(ws)
    if sw <= 0:
        return (ys[-1] if ys else 0.0), 0.0
    mx = sum(w * x for x, w in zip(xs, ws)) / sw
    my = sum(w * y for y, w in zip(ys, ws)) / sw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    if sxx <= 1e-12:
        return my, 0.0
    sxy = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws))
    b = sxy / sxx
    return my - b * mx, b


def distinct_states(history):
    """Collapse consecutive identical reads into refresh states.

    A read is (players_tracked, rates); Exophase republishes on its own
    schedule, so the same state repeats until the next refresh. Returns a
    list of (time_hours_since_first_read, players_tracked, rates).
    """
    states = []
    prev_key = None
    t0 = None
    for read in history:
        stamp = read.get("slot") or read.get("at")
        if stamp is None:
            continue
        t = parse_time(stamp)
        if t0 is None:
            t0 = t
        rates = read.get("rates") or []
        key = (read.get("players_tracked"), tuple(rates))
        if key != prev_key:
            states.append(((t - t0) / 3600.0, read.get("players_tracked"), list(rates)))
            prev_key = key
    return states


def trim_regime(pts):
    """Drop early points from a different pool regime.

    pts is a list of (x, size, ...) points in time order. The pre-launch
    pool (hundreds of tracked players) is not the launch pool (hundreds
    of thousands): while the pool is under 2% of its last size it is a
    different population, and its points wreck any trend fit. Keep the
    points from the first one that reaches 2% of the last size, but
    never keep fewer than the last four points.
    """
    if len(pts) <= 4:
        return pts
    n_last = pts[-1][1]
    start = 0
    for k, p in enumerate(pts):
        if p[1] >= 0.02 * n_last:
            start = k
            break
    start = min(start, len(pts) - 4)
    return pts[start:]


def forecast_players(states, horizon_h, age_h):
    """Forecast the tracked-pool size at the target.

    states: distinct refresh states; horizon_h: hours from the last state
    to the target; age_h: hours from the first read to the last state.
    """
    pts = [(x, n) for (x, n, _rates) in states if n]
    if not pts:
        return None
    pts = trim_regime(pts)
    x_last, n_last = pts[-1]
    x_target = x_last + horizon_h
    if len(pts) >= 3:
        # Power law in time: ln N against ln(1 + x), recency-weighted.
        xs = [math.log1p(x) for x, _n in pts]
        ys = [math.log(n) for _x, n in pts]
        ws = [0.55 + 0.45 * (k / (len(pts) - 1)) for k in range(len(pts))]
        a, b = wls_line(xs, ys, ws)
        b = min(max(b, 0.0), 3.0)
        n_power = math.exp(a + b * math.log1p(x_target))
        # Recent growth, damped: growth over the last day (or the whole
        # span, if shorter), extrapolated with a saturation damper.
        span = x_last - pts[0][0]
        window = min(24.0, span) if span > 0 else 0.0
        recent = [(x, n) for x, n in pts if x >= x_last - window] or pts[-2:]
        if len(recent) >= 2 and recent[-1][0] > recent[0][0]:
            g = math.log(recent[-1][1] / recent[0][1]) / (recent[-1][0] - recent[0][0])
        else:
            g = 0.0
        g = min(max(g, 0.0), 0.35)
        n_exp = n_last * math.exp(g * horizon_h / (1.0 + horizon_h / 96.0))
        # The damped recent growth is the primary estimate; the power
        # law, which extrapolates the whole launch curve, only moderates
        # it. Early explosive growth makes the power law overshoot.
        n_star = math.exp(0.65 * math.log(max(n_exp, 1.0)) + 0.35 * math.log(max(n_power, 1.0)))
    elif len(pts) == 2:
        (x_a, n_a), (x_b, n_b) = pts
        if x_b > x_a and n_a > 0:
            g = math.log(n_b / n_a) / (x_b - x_a)
        else:
            g = 0.0
        g = min(max(g, 0.0), 0.35)
        n_star = n_last * math.exp(g * horizon_h * 0.6)
    else:
        # One refresh state only: no trend is visible. Launch prior: the
        # pool multiplies as the launch influx is ingested, fastest in the
        # first hours after release.
        factor = 1.0 + 2.2 * math.sqrt(max(horizon_h, 0.0)) * math.exp(-max(age_h, 0.0) / 24.0)
        n_star = n_last * min(factor, 12.0)
    # The tracked pool does not shrink, and no sane week-one pool is more
    # than two hundred times the last observed one.
    return min(max(n_star, float(n_last)), float(n_last) * 200.0)


def forecast_earners(states, idx, horizon_h, age_h, n_star):
    """Forecast the earner count of trophy `idx` at the target.

    Returns (earners_at_target, earners_at_last_state, last_rate).
    """
    pts = []   # (x, earners, rate) for each state with a usable rate
    pool = []  # the pool size of that state, for regime trimming
    for (x, n, rates) in states:
        if n and idx < len(rates) and rates[idx] is not None:
            pts.append((x, rates[idx] * n / 100.0, rates[idx]))
            pool.append(n)
    if not pts:
        return None, None, None
    x_last, e_last, r_last = pts[-1]
    # Fit on the current pool regime only (see trim_regime): drop the
    # points before the pool reached 2% of its last size, keeping at
    # least the last four, and drop interior points whose earner count
    # is under one whole player (rounding noise, not signal). The last
    # point always stays: it is the anchor every forecast starts from.
    if len(pts) > 4:
        start = 0
        for k, n in enumerate(pool):
            if n >= 0.02 * pool[-1]:
                start = k
                break
        start = min(start, len(pts) - 4)
        trimmed = pts[start:]
        fit = [p for p in trimmed[:-1] if p[1] >= 1.0] + [trimmed[-1]]
        if len(fit) >= 2:
            pts = fit
    x_target = x_last + horizon_h
    if r_last >= 99.9:
        # Held by (essentially) every tracked player: it grows with the
        # pool itself, so its rate stays where it is.
        return n_star * r_last / 100.0, e_last, r_last
    if len(pts) >= 3:
        # Power law in time for the cumulative earner count, fitted on
        # ln(E + 0.5) against ln(1 + x) with recency weights; the slope is
        # shrunk toward flat, more when there are fewer states to fit.
        xs = [math.log1p(x) for x, _e, _r in pts]
        ys = [math.log(e + 0.5) for _x, e, _r in pts]
        ws = [0.55 + 0.45 * (k / (len(pts) - 1)) for k in range(len(pts))]
        a, b = wls_line(xs, ys, ws)
        shrink = len(pts) / (len(pts) + 3.0)
        b = min(max(b * shrink, 0.0), 2.2)
        e_power = math.exp(a + b * math.log1p(x_target)) - 0.5
        # Recent-segment growth of the same count, damped.
        span = x_last - pts[0][0]
        window = min(24.0, span) if span > 0 else 0.0
        recent = [p for p in pts if p[0] >= x_last - window] or pts[-2:]
        if len(recent) >= 2 and recent[-1][0] > recent[0][0] and recent[0][1] > 0:
            g = math.log((recent[-1][1] + 0.5) / (recent[0][1] + 0.5)) / (recent[-1][0] - recent[0][0])
        else:
            g = 0.0
        g = min(max(g, 0.0), 0.30)
        e_seg = e_last * math.exp(g * horizon_h * 0.65)
        e_star = math.sqrt(max(e_power, 0.0) * max(e_seg, 0.0)) if e_power > 0 else e_seg
    elif len(pts) == 2:
        (x_a, e_a, _ra), (x_b, e_b, _rb) = pts
        if x_b > x_a and e_a > 0 and e_b > 0:
            ratio = (e_b / e_a) ** (0.65 * horizon_h / (x_b - x_a))
            e_star = e_b * min(max(ratio, 1.0), 50.0)
        else:
            e_star = e_b
    else:
        # One refresh state only: launch prior. Earners grow, but far more
        # slowly than the ingested pool; trophies that are already common
        # (early, easy ones) are picked up by newcomers fastest.
        reach = 0.45 + 0.55 * (min(r_last, 25.0) / 25.0)
        growth = 1.0 + 1.15 * math.sqrt(max(horizon_h, 0.0)) * math.exp(-max(age_h, 0.0) / 24.0) * reach
        e_star = e_last * growth
    # Earner counts are cumulative: they never go down. And no trophy can
    # be held by more players than the pool holds.
    e_star = max(e_star, e_last)
    e_star = min(e_star, n_star)
    return e_star, e_last, r_last


def realized_volatility(states):
    """Median absolute logit move per square-root day between refreshes.

    Measured on the case's own distinct states, across every trophy with
    a usable rate in both of two consecutive states. Returns None when
    there are too few transitions to measure anything.
    """
    moves = []
    for (x_a, _na, rates_a), (x_b, _nb, rates_b) in zip(states, states[1:]):
        dt_days = (x_b - x_a) / 24.0
        if dt_days <= 0:
            continue
        scale = math.sqrt(dt_days)
        for r_a, r_b in zip(rates_a, rates_b):
            if r_a is None or r_b is None:
                continue
            if 0.05 < r_a < 99.95 and 0.05 < r_b < 99.95:
                moves.append(abs(logit(r_b) - logit(r_a)) / scale)
    if len(moves) < 8:
        return None
    moves.sort()
    return moves[len(moves) // 2]


def pool_earners(raw):
    """Partially pool the per-trophy earner forecasts.

    raw: list of (earners_at_target, earners_at_last, last_rate) per
    trophy, with None where a trophy has no usable history. A trophy held
    by four players has a very noisy growth fit; shrinking its growth
    factor toward the median growth factor across trophies (in log space,
    weighted by how many earners back the fit) trades a little bias for a
    lot of variance. Trophies already held by essentially everyone are
    left alone: their growth is the pool's growth, not a fit.
    """
    factors = []
    for item in raw:
        if item is None:
            continue
        e_star, e_last, r_last = item
        if e_last and e_last > 0 and r_last is not None and r_last < 99.9:
            factors.append(e_star / e_last)
    if len(factors) < 5:
        return raw
    factors.sort()
    g_common = factors[len(factors) // 2]
    pooled = []
    for item in raw:
        if item is None:
            pooled.append(None)
            continue
        e_star, e_last, r_last = item
        if not e_last or e_last <= 0 or r_last is None or r_last >= 99.9 or e_star <= 0:
            pooled.append(item)
            continue
        w = e_last / (e_last + 8.0)
        blended = math.exp(w * math.log(e_star) + (1.0 - w) * math.log(e_last * g_common))
        pooled.append((blended, e_last, r_last))
    return pooled


def persistence_forecast(case):
    """The house baseline, used only if the main model cannot run."""
    last = case["history"][-1]
    spread = 0.5 * math.sqrt(case["horizon_minutes"] / 1440.0)
    rows = []
    for i, trophy in enumerate(case["trophies"]):
        rate = last["rates"][i]
        lg = logit(rate if rate is not None else 0.0)
        rows.append({"id": trophy["id"], "q": [round4(logistic(lg + z * spread)) for z in Z]})
    return {"trophies": rows}


def forecast_case(case, name):
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    history = case.get("history") or []
    if not history:
        raise ValueError(f"{name} has no history")
    trophies = case["trophies"]
    # Anchor times on the case itself: the checkpoint and the target.
    t_at = parse_time(case["at"])
    t_target = parse_time(case["target"]) if case.get("target") else t_at + case["horizon_minutes"] * 60
    horizon_h = max((t_target - t_at) / 3600.0, 0.0)
    horizon_d = horizon_h / 24.0
    states = distinct_states(history)
    if not states:
        return persistence_forecast(case)
    age_h = states[-1][0]
    n_last = states[-1][1]
    n_star = forecast_players(states, horizon_h, age_h)
    if not n_star:
        return persistence_forecast(case)
    n_refreshes = len(states)
    refresh_sigma = REFRESH_SIGMA_SEEN * math.sqrt(max(horizon_d, 0.0)) if n_refreshes >= 3 else REFRESH_SIGMA_UNSEEN
    # The random-walk part of the spread blends the fixed prior with the
    # volatility the case's own refreshes actually showed.
    vol = realized_volatility(states)
    if vol is None:
        rw_sigma = BASE_SIGMA
    else:
        rw_sigma = 0.45 * BASE_SIGMA + 0.55 * min(max(vol, 0.2), 1.6)
    base_sigma = math.sqrt((rw_sigma * math.sqrt(max(horizon_d, 0.0))) ** 2 + refresh_sigma ** 2)
    raw = []
    for i in range(len(trophies)):
        item = forecast_earners(states, i, horizon_h, age_h, n_star)
        raw.append(item if item is not None and item[0] is not None else None)
    raw = pool_earners(raw)
    rows = []
    for i, trophy in enumerate(trophies):
        item = raw[i]
        if item is None:
            # The trophy never appears in any read: fall back on its last
            # listed rate if there is one, else a low, wide guess.
            last_rates = history[-1].get("rates") or []
            r_last = last_rates[i] if i < len(last_rates) else None
            median = r_last if r_last is not None else 0.5
            sigma = SIGMA_CAP
        else:
            e_star, e_last, r_last = item
            # Re-apply the cumulative floor and the pool cap after
            # pooling, then cap the median's move from the last rate.
            e_star = min(max(e_star, e_last), n_star)
            median = 100.0 * e_star / n_star
            if r_last is not None and r_last < 99.9:
                centre = logit(median)
                anchor = logit(r_last)
                centre = min(max(centre, anchor - MAX_MEDIAN_MOVE), anchor + MAX_MEDIAN_MOVE)
                median = logistic(centre)
            # Trophies held by a handful of players move in whole-player
            # steps: widen their spread by the counting noise.
            noise = 1.0 + 0.45 / math.sqrt(e_last + 1.0)
            sigma = min(base_sigma * noise, SIGMA_CAP)
        centre = logit(median)
        quantiles = sorted(round4(logistic(centre + z * sigma)) for z in Z)
        rows.append({"id": trophy["id"], "q": quantiles})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            forecast = forecast_case(case, path.name)
        except Exception:
            forecast = persistence_forecast(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
