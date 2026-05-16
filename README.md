# autoratiorr

Align qBittorrent share limits for torrents injected by cross-seed.

When cross-seed injects a duplicate torrent into qBittorrent, this script finds the
matching source torrent and sets the cross-seed torrent's `seedingTimeLimit` so the
two torrents reach their seeding-time limit at the same time.

## Behavior

- Logs in to qBittorrent Web API.
- Reads cross-seed torrents from configured categories.
- Finds matching source torrents outside that category and without the `cross-seed`
  tag.
- Falls back to qBittorrent file-list matching when torrent names differ. The
  fallback first narrows candidates by total size, then matches file sizes while
  allowing small extra files on the injected torrent.
- Skips file-list fallback matches when multiple source torrents match, so seed
  limits are not aligned to an ambiguous source.
- Calculates the cross-seed torrent's total seed-time limit from qBittorrent's
  elapsed `seeding_time` fields.
- Caches only successfully updated torrents so failed or dry-run updates are retried.

qBittorrent uses minutes for `setShareLimits` and seconds for elapsed
`seeding_time`, so the script converts between those units before setting limits.

## Configuration

Required environment variables:

```bash
QB_URL=http://localhost:8080
QB_USERNAME=admin
QB_PASSWORD=adminadmin
CAT_NAMES='["cross-seed"]'
```

`CAT_NAMES` can be a JSON array or a comma-separated string. `CATEGORY_NAME` is also
accepted as a fallback for single-category setups.

Optional environment variables:

```bash
DRY_RUN=false
SCHEDULE=30
CACHE_EXPIRY_DAYS=14
CACHE_FILE=torrent_cache.json
MATCH_THRESHOLD=1
PARTIAL_MATCH_MAX_EXTRA_BYTES=52428800
REQUEST_TIMEOUT=30
LOG_LEVEL=INFO
```

Set `SCHEDULE=0` to run once and exit.

## Run Locally

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
python script.py
```

Run tests:

```bash
python -m unittest discover -s tests
```
