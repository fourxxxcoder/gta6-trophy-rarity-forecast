# gta6-trophy-rarity-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/fourxxxcoder/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/fourxxxcoder/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A forecaster for the earn rate of every Grand Theft Auto VI PlayStation 5 trophy on Exophase one week after launch. The program reads a case file — every read of the game's Exophase trophy page before the case's checkpoint — and writes five quantiles (5%, 25%, 50%, 75%, 95%) of each trophy's earn rate at the target. It never forecasts a rate directly: it decomposes each rate into earners over players tracked, forecasts the tracked pool and each trophy's cumulative earner count separately on the distinct Exophase refresh states, partially pools the per-trophy growth fits, and takes logistic-normal quantiles with a spread blended from the case's own refresh volatility. Standard library only, fully deterministic, no network.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## How it works

* `main.py` is the whole entry (Python 3.13, standard library only). It
  reads every `<id>.in` in `$MAKEFUN_INPUT_DIR` (default `/input`) and
  writes `<id>.out` to `$MAKEFUN_OUTPUT_DIR` (default `/output`), in the
  case format the bounty specifies.
* [METHODOLOGY.md](METHODOLOGY.md) explains the earners/players
  decomposition, the refresh-state fitting, the launch prior used when
  a history holds a single refresh state, how the spread is built, and
  the published trophy data for comparable games (GTA V, Red Dead
  Redemption 2, Ghost of Tsushima and others) that anchors the priors.

---
<sub>Entered on [make.fun](https://make.fun/?ref=7z89ba3s&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
