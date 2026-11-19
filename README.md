[![make.fun](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Rizkiarr/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Rizkiarr/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)

# GTA VI Trophy Rarity Forecast

Forecasts how many GTA VI players earn each of the game's 55 trophies in week one.

`main.py` (Python 3.13, standard library only) reads one case file and writes, for each trophy, the 5/25/50/75/95% quantiles of its earn rate at the case target. It fits a logit-linear trend of each trophy's Exophase earn rate against log-hours since launch, with tier-based drift for flat trends and a horizon-growing spread.

Built for the [make.fun bounty](https://make.fun/bounty/gta6-trophy-rarity-forecast-01).
