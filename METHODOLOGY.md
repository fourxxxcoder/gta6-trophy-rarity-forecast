# Methodology

## What is being forecast

For each of Grand Theft Auto VI's 55 PlayStation 5 trophies, the earn rate
printed on Exophase's trophy page for the game at the target time
(2026-11-26 00:00 UTC): the percent of the players Exophase tracks for the
game who have earned that trophy. The entry is a program, `main.py`, that
reads a case file (every read the house made of that page before the
case's checkpoint) and writes five quantiles (5%, 25%, 50%, 75%, 95%) of
each trophy's earn rate at the target. Scoring is mean pinball loss on
the logit scale, so rare and common trophies weigh equally and an honest
spread scores as well as an accurate median.

## The decomposition

An earn rate is a ratio, and the two sides of the ratio move for
different reasons, so they are forecast separately:

    earn rate = earners / players_tracked

* **players_tracked** is the size of Exophase's tracked pool. It grows as
  Exophase ingests new players. At the first refresh after launch it
  multiplied by six (638 → 3,868) in a few hours; growth then
  decelerates as the pool mainstreams.
* **earners** of a trophy is the implied count behind the rate
  (rate × players_tracked / 100). It is a cumulative count: it never
  decreases. It grows as the existing cohort progresses through the game
  and as newcomers reach the trophy.

Forecasting the rate directly (the house curve baseline fits a line to
the logit rate) mixes the two motions together: a rate can fall while
every player is progressing, purely because the pool grew faster. The
decomposition keeps dilution and progression separate, which is what the
launch-week data actually does.

## Refresh states, not reads

Exophase republishes its counts on its own schedule, so the page is a
step function: the house's reads repeat one state until the next
refresh. Only the distinct states carry trend information, so every fit
runs on the deduplicated states. The pre-launch pool (638 tracked
players, a different population from the launch pool) poisons trend
fits, so points are also trimmed to the current pool regime: fitting
starts at the first state whose pool is at least 2% of the last state's
pool, always keeping at least the last four states.

## The two forecasts

* **Pool.** A power law in time (ln N against ln(1 + hours since the
  first read), recency-weighted least squares) blended 35/65 with a
  damped extrapolation of the last day's growth rate. The damped recent
  growth leads because the power law extrapolates the explosive first
  hours and overshoots; in simulation it forecast a 2.8M pool where the
  truth was 1.05M before this weighting, and tracks closely after it.
* **Earners, per trophy.** A power law in time for the cumulative count
  (ln(E + 0.5) against ln(1 + hours), recency-weighted, slope shrunk by
  K/(K + 3) for K fitted states and capped at 2.2), blended geometrically
  with a damped extrapolation of the count's recent growth. The result
  is floored at the last observed count (cumulative counts do not fall)
  and capped at the forecast pool size.

Per-trophy fits are then **partially pooled**: a trophy held by four
players has a growth factor estimated from almost nothing, so each
trophy's growth factor is shrunk toward the median growth factor across
trophies, in log space, with weight E/(E + 8) for E last earners. A
trophy held by essentially every tracked player (the 100% opener) is
exempt: it grows with the pool itself, so its rate stays put.

The median's move from the last observed rate is capped at 4.5 logit
units (about a 90-fold odds move), so a runaway fit cannot produce an
absurd week-one rate.

## When there is no trend to fit

The launch-night practice cases hold a single refresh state: the first
refresh has not happened yet, and no trend exists. The forecaster then
uses a launch prior: the pool is expected to multiply as the launch
influx is ingested (fastest in the first hours), earners grow much more
slowly (trophies that are already common are picked up by newcomers
fastest), so most medians are diluted down from their last rates, and
the predictive spread is set very wide (see below) to price a refresh
that has not been seen. This is exactly the situation the house baseline
fails: it scored about 1.51 on the practice with 90% coverage of about
0, because the refresh took every rate outside its narrow band.

## The spread

Each trophy's predictive distribution is logistic-normal: quantiles are
taken on the logit scale around the forecast median. The total spread
combines, in quadrature:

* a random-walk term, sigma_rw × sqrt(horizon in days), where sigma_rw
  blends a fixed prior (0.55 per root-day) with the volatility the case's
  own refreshes actually showed (the median absolute logit move per
  root-day between consecutive distinct states, across trophies);
* a refresh-uncertainty term: 0.30 × sqrt(horizon in days) once
  refreshes have been observed, and a flat 1.05 logit units when none
  has (the unseen-refresh case above);
* per trophy, a counting-noise multiplier 1 + 0.45/sqrt(E + 1) for E
  last earners, because a trophy held by a handful of players moves in
  whole-player steps.

The total is capped at 2.9 logit units.

## Why these shapes: comparable games

The priors are anchored in published trophy/achievement data for
comparable games (researched November 2026):

* **Progression is slow and saturating.** Lifetime story-completion
  rates for big open-world games on PlayStation sit at roughly 20–50%:
  Marvel's Spider-Man 50.8%, Ghost of Tsushima 50.2%, Assassin's Creed
  Origins 38.2%, The Witcher 3 29.8%, Red Dead Redemption 2 28.2%,
  Assassin's Creed Valhalla 19.8% (UnGeek's trophy report). GTA V's
  final-mission trophy sits at about 16.8% (PS4) to 29.4% (PS5) after
  years, and its platinum at 0.1%. A 2026 audit of 19 single-player
  games put the median lifetime completion at 36%. Week-one rates are
  far below these ceilings, and late-story trophies move slowly — which
  is why earner growth is modelled as a decelerating power law, not a
  line, and why the platinum's median stays near zero.
* **Early rates run hot, then dilute.** Horizon Forbidden West had 14%
  story completion three weeks after launch, on pace for its
  predecessor's 32% lifetime figure: progression keeps accumulating for
  weeks while the tracked pool mainstreams. Tracker pools are
  self-selected — Kwak's 2022 comparison of PSNProfiles against PSN-wide
  rates shows tracker-site rates skew high — so a tracker page like
  Exophase's starts with unusually engaged players and dilutes as it
  grows, exactly the motion the earners/players decomposition separates.
* **Published rates can invert story order.** GTA V's final-mission
  trophy (16.8%) sits above an earlier required story trophy (15.3%) in
  published data, thanks to cheats, mission skips and offline sync. The
  model therefore does not force chapter trophies into a monotone order;
  it pools growth factors instead of imposing a false constraint.

## Validation

There is no local grade for this competition; the server grades every
entry. The forecaster was validated three ways:

1. **Format and determinism** on the kit's practice cases (p00, p01):
   valid output shape, and two runs byte-identical.
2. **Simulation.** A synthetic final case was built from a cohort model
   (players arrive on a saturating curve; each earns a trophy after a
   lognormal delay; the page refreshes every five hours) in three
   regimes — hot progression, cool progression, and dilution-dominated —
   and scored with the contest's pinball loss against the persistence
   baseline. The forecaster beat persistence in all three (0.70 vs 1.17,
   1.26 vs 1.53, 1.50 vs 1.96). The regime trimming and the pool blend
   weights above were set by what this simulation exposed.
3. **The practice cases** exercise the single-state launch prior: the
   medians dilute down from the last rates (a 1.10% trophy is forecast
   at a 0.50% median) with a wide spread, instead of the baseline's
   stay-put median and narrow band.

## Limits

* Exophase's refresh cadence and the tracked pool's composition are
  outside the case data; the spread prices them but cannot remove them.
* Rates are printed to two decimals, so implied earner counts for rare
  trophies are quantised to whole players; the counting-noise term in
  the spread is the model's allowance for that.
* The final case's history (2.5 days) is much richer than the practice
  histories (one state), so the trend machinery — the part that matters
  most — is validated by simulation rather than by the practice score.
