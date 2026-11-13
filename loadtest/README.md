# Load test

[k6](https://grafana.com/docs/k6/) script for the photo analysis, the expensive path of the
application (detector, then language model). It runs from a container, so k6 does not need
to be installed.

## What it does

`analyze.js` starts analyses at a fixed rate per minute, whether earlier ones have
finished or not, the way independent users would arrive (k6 executor
`ramping-arrival-rate`). Every virtual user logs in once and then uploads a random photo
from the given directory.

| Profile | Analyses started per minute |
|---|---|
| `smoke` | 4 for one minute: checks the script and the deployment |
| `ramp` (default) | 6, 12, 24, 36, 48, two minutes each |

Reported per answer: status code, `description_source` (`llm`, `template`, `no_damage`),
and the time until the answer (`analysis_seconds`). Raw samples go to
`loadtest/results/results.csv`, the summary to `loadtest/results/summary.json` (both
ignored by git).

## Running it

All virtual users share one client address. The application's limits per address
(20 analyses and 10 logins per window) and the gateway's (120 requests per minute) would
reject most of the test, so a test deployment raises them with
`deploy/helm/roadscan/values-loadtest.yaml`, and the normal values are deployed again
afterwards.

```bash
# AKS: deploy the current image with raised limits
make deploy TAG=<tag> VALUES="-f deploy/helm/roadscan/values-loadtest.yaml"

ROADSCAN_DEMO_PASSWORD=... make loadtest \
  URL=https://<host> PHOTOS=<directory with road photos> PROFILE=ramp

make deploy TAG=<tag>    # limits back to normal
```

Watch it in Grafana (`make grafana`, dashboard "RoadScan"): the queue in front of the
`Describer` and the analysis latency show where the application saturates.

Photos: any road photos work. The results in the main README used images from the
RDD2022 test split (Japan, India, Czech), which are not part of the repository.
