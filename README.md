# autoratiorr

Align qBittorrent share limits for torrents injected by cross-seed.

When cross-seed injects a duplicate torrent into qBittorrent, this script finds the
matching source torrent and sets the cross-seed torrent's `seedingTimeLimit` so the
two torrents reach their seeding-time limit at the same time.

## Behavior

- Logs in to qBittorrent Web API.
- Reads cross-seed torrents from configured categories.
- Finds matching source torrents outside that category and its subcategories,
  and without the `cross-seed` tag.
- Falls back to qBittorrent file-list matching when torrent names differ. The
  fallback first narrows candidates by total-size difference, then matches file
  sizes while allowing small extra files on either torrent. Unmatched bytes on
  each side must stay within `PARTIAL_MATCH_MAX_EXTRA_BYTES`, and shared files
  must account for more bytes than the unmatched files on either side.
- Skips file-list fallback matches when multiple source torrents match, so seed
  limits are not aligned to an ambiguous source.
- Calculates the cross-seed torrent's total seed-time limit from qBittorrent's
  elapsed `seeding_time` fields.
- Caches only successfully updated torrents so failed or dry-run updates are retried.

qBittorrent uses minutes for `setShareLimits` and seconds for elapsed
`seeding_time`, so the script converts between those units before setting limits.

## qBittorrent Compatibility

Checked against qBittorrent **5.2.3** using an isolated official container and
synthetic torrents: login/session cookies, category/tag queries, file-list
matching, share-limit writes/read-back, elapsed-time alignment, dry-run, and
successful-update caching.

- `setShareLimits` includes the required `shareLimitAction`, preserving the
  cross-seed torrent's existing action.
- Inherited source limits use `max_seeding_time`, which resolves category/global
  settings, including unlimited (`-1`) and zero-minute limits.
- Source exclusion mirrors category queries, which include subcategories.

Contracts were verified against the
[5.2.3 API handlers](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/torrentscontroller.cpp)
and [torrent serialization](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/serialize/serialize_torrent.cpp).
This does not verify a deployment's proxy or authentication configuration.

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

## Troubleshoot Unmatched Torrents

`stoppedUP` and `stalledUP` torrents are processed normally. A
`No matching source torrent` message means neither name matching nor file-list
matching found a unique source under the current rules:

- Sources must be in the same qBittorrent instance, outside the processed category
  and its subcategories, and without the `cross-seed` tag. The `Source torrent
  pool` log reports total torrents and eligible sources.
- `MATCH_THRESHOLD=1` requires identical sets of name tokens after case,
  punctuation, and common video extensions are normalized.
- `reason=no_size_candidates` means no eligible source has a total size within
  `PARTIAL_MATCH_MAX_EXTRA_BYTES` of the injected torrent (50 MiB by default).
- `reason=cross_seed_files_unavailable` means the injected torrent's file list
  could not be read or was empty.
- `reason=no_file_match` means no source file list matched. Check
  `unavailable_file_lists` for source file-list retrieval failures.
- `ambiguous source` means multiple source file lists matched, so the script
  skipped alignment.

For a diagnostic run, set `DRY_RUN=true`, `SCHEDULE=0`, and `LOG_LEVEL=DEBUG`.
DEBUG output includes rejected file-list candidates with source hashes and names.
If a torrent remains unmatched, compare its source and injected torrent names,
categories, tags, total sizes, and file lists. Torrents injected from standalone
files may have no source torrent in qBittorrent to align with.

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
