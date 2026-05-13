import json
import math
import os
import re
import time
from datetime import datetime, timedelta

import requests
from requests.exceptions import RequestException


def get_env_variable(var_name):
    value = os.getenv(var_name)
    if value is None:
        raise EnvironmentError(f"The environment variable {var_name} is not set.")
    try:
        # Try to parse the value as JSON
        value = json.loads(value)
    except json.JSONDecodeError:
        # If it's not a valid JSON string, just return the original string
        pass

    return value


def get_env_list(var_name, fallback_var_name=None):
    raw_value = os.getenv(var_name)
    if raw_value is None and fallback_var_name:
        raw_value = os.getenv(fallback_var_name)
    if raw_value is None:
        raise EnvironmentError(f"The environment variable {var_name} is not set.")

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    raise EnvironmentError(f"The environment variable {var_name} must be a list or string.")


CACHE_EXPIRY_DAYS = int(os.getenv("CACHE_EXPIRY_DAYS", "14"))
CACHE_FILE = os.getenv("CACHE_FILE", "torrent_cache.json")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ["true", "1", "t"]
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "1"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
SCHEDULE = int(os.getenv("SCHEDULE", "30"))
QB_URL = get_env_variable("QB_URL")
QB_USERNAME = get_env_variable("QB_USERNAME")
QB_PASSWORD = get_env_variable("QB_PASSWORD")
CAT_NAMES = get_env_list("CAT_NAMES", fallback_var_name="CATEGORY_NAME")

session = requests.Session()

UNHEALTHY_CROSS_SEED_STATES = {"error", "missingFiles"}


def read_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
            # Remove expired cache entries
            now = datetime.now()
            cache = {
                k: v
                for k, v in cache.items()
                if datetime.fromisoformat(v) + timedelta(days=CACHE_EXPIRY_DAYS) > now
            }
            return cache
    except json.JSONDecodeError:
        # If there is a JSON decode error, return an empty dictionary
        return {}


def write_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=4)


def is_torrent_cached(torrent_hash, cache):
    """Check if the torrent is in the cache and if the cache is still valid."""
    return torrent_hash in cache


def cache_torrent(torrent_hash, cache):
    """Cache the torrent with the current timestamp."""
    cache[torrent_hash] = datetime.now().isoformat()
    write_cache(cache)


def qb_login(url, username, password):
    login_url = f"{url}/api/v2/auth/login"
    data = {"username": username, "password": password}
    try:
        response = session.post(login_url, data=data, timeout=REQUEST_TIMEOUT)
        if response.text.strip() == "Ok.":
            print("Login successful")
            return True
        print(f"Login failed. Status code: {response.status_code}")
        return False
    except RequestException as e:
        print(f"Error logging in: {e}")
        return False


def get_torrents_by_category(url, category_name):
    torrents_url = f"{url}/api/v2/torrents/info"
    params = {"filter": "all", "category": category_name}
    try:
        response = session.get(torrents_url, params=params, timeout=REQUEST_TIMEOUT)
        if response.ok:
            torrents = response.json()
            return torrents
        else:
            print("Could not get torrent list")
            return None
    except RequestException as e:
        print(f"Error retrieving torrents: {e}")
        return None


def get_torrents_excluding_category_and_tag(url, category_name, tag_name):
    torrents_url = f"{url}/api/v2/torrents/info"
    params = {"filter": "all"}

    try:
        response = session.get(torrents_url, params=params, timeout=REQUEST_TIMEOUT)
        if response.ok:
            torrents = response.json()
            # Prepare the tag_name to be searched within torrent tags
            tag_to_exclude = tag_name.strip()

            filtered_torrents = [
                torrent
                for torrent in torrents
                if (
                    torrent.get("category") != category_name
                    and tag_to_exclude
                    not in [tag.strip() for tag in torrent.get("tags", "").split(",")]
                )
            ]
            return filtered_torrents
        else:
            print("Could not get torrent list. Status code:", response.status_code)
            return None
    except requests.RequestException as e:
        print(f"Error retrieving torrents: {e}")
        return None


def get_torrents_by_tag(url, tag_name):
    torrents_url = f"{url}/api/v2/torrents/info"
    params = {"filter": "all", "tag": tag_name}
    try:
        response = session.get(torrents_url, params=params, timeout=REQUEST_TIMEOUT)
        if response.ok:
            torrents = response.json()
            return torrents
        else:
            print("Could not get torrent list")
            return None
    except RequestException as e:
        print(f"Error retrieving torrents: {e}")
        return None


def set_torrent_seed_limits(
    url,
    torrent_hash,
    seed_time,
    share_ratio,
    dry_run=False,
):
    set_limits_url = f"{url}/api/v2/torrents/setShareLimits"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "hashes": torrent_hash,
        "seedingTimeLimit": seed_time,
        "ratioLimit": share_ratio,
        "inactiveSeedingTimeLimit": -1,
    }
    if dry_run:
        print(
            "Dry run: Would set seed limits for torrent "
            + f"{torrent_hash} with seedingTimeLimit {seed_time} "
            + f"and ratioLimit {share_ratio}"
        )
        return False
    try:
        response = session.post(
            set_limits_url,
            headers=headers,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )
        if response.ok:
            print(f"Seed limits set for torrent {torrent_hash}")
            return True
        print(
            f"Failed to set seed limits for torrent {torrent_hash}. "
            + f"Status code: {response.status_code}"
        )
        return False
    except RequestException as e:
        print(f"Error setting seed limits: {e}")
        return False


def int_field(torrent, field_name, default=0):
    try:
        return int(torrent.get(field_name, default))
    except (TypeError, ValueError):
        return default


def get_effective_seed_limit_minutes(torrent):
    seed_limit = int_field(torrent, "seeding_time_limit", -2)
    if seed_limit >= 0:
        return seed_limit

    max_seeding_seconds = int_field(torrent, "max_seeding_time", seed_limit)
    if seed_limit == -2 and max_seeding_seconds > 0:
        return math.ceil(max_seeding_seconds / 60)

    return seed_limit


def calculate_aligned_seed_time_limit(original_torrent, cross_seed_torrent):
    seed_limit = get_effective_seed_limit_minutes(original_torrent)
    if seed_limit in (-1, -2):
        return seed_limit

    original_elapsed_seconds = max(0, int_field(original_torrent, "seeding_time", 0))
    cross_elapsed_seconds = max(0, int_field(cross_seed_torrent, "seeding_time", 0))
    remaining_seconds = (seed_limit * 60) - original_elapsed_seconds
    cross_total_limit_seconds = cross_elapsed_seconds + remaining_seconds

    return max(0, math.ceil(cross_total_limit_seconds / 60))


def get_time_difference(original_added_on, cross_added_on, seeding_time_limit):
    if seeding_time_limit in (-1, -2):
        return seeding_time_limit

    # convert epoch time to datetime object
    time = datetime.fromtimestamp(original_added_on)

    # add minutes
    new_time = time + timedelta(minutes=seeding_time_limit)

    # calculate the difference
    cross_time = datetime.fromtimestamp(cross_added_on)
    time_diff = new_time - cross_time

    # convert the difference to minutes and round it up
    minutes_diff = math.ceil(time_diff.total_seconds() / 60)

    return max(0, minutes_diff)


def jaccard_similarity(str1, str2):
    # List of known video file extensions
    video_extensions = [".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv"]

    # Remove video file extension if it exists
    for ext in video_extensions:
        if str1.lower().endswith(ext):
            str1 = str1[: -len(ext)]
        if str2.lower().endswith(ext):
            str2 = str2[: -len(ext)]

    set1 = {part for part in re.split(r"[\W_]+", str1.lower()) if part}
    set2 = {part for part in re.split(r"[\W_]+", str2.lower()) if part}
    if not set1 or not set2:
        return 0
    return len(set1.intersection(set2)) / len(set1.union(set2))


def find_matching_original_torrent(original_torrents, cross_seed_torrent):
    for original_torrent in original_torrents:
        if (
            jaccard_similarity(
                original_torrent["name"],
                cross_seed_torrent["name"],
            )
            >= MATCH_THRESHOLD
        ):
            return original_torrent
    return None


def is_processable_cross_seed(torrent):
    return torrent.get("state") not in UNHEALTHY_CROSS_SEED_STATES


def main():
    if not qb_login(QB_URL, QB_USERNAME, QB_PASSWORD):
        return

    cache = read_cache()
    updated_count = 0
    print(f"handling torrents with cat: {CAT_NAMES}")
    for cat_name in CAT_NAMES:
        print(f"handling torrents with cat: {cat_name}")
        cross_seed_torrents = get_torrents_by_category(QB_URL, cat_name)
        if not cross_seed_torrents:
            continue

        original_torrents = get_torrents_excluding_category_and_tag(
            QB_URL,
            cat_name,
            "cross-seed",
        )
        if not original_torrents:
            continue

        for torrent in cross_seed_torrents:
            if is_torrent_cached(torrent["hash"], cache):
                continue
            print(f"Name: {torrent['name']}")
            print(f"State: {torrent['state']}")
            print(f"Hash: {torrent['hash']}")
            print("---")
            if not is_processable_cross_seed(torrent):
                print(f"Skipping unhealthy cross-seed torrent: {torrent['state']}")
                print("---")
                continue

            original_torrent = find_matching_original_torrent(original_torrents, torrent)
            if not original_torrent:
                continue

            print(f"Found original torrent: {original_torrent['hash']}")
            seeding_time_limit = calculate_aligned_seed_time_limit(
                original_torrent,
                torrent,
            )
            if set_torrent_seed_limits(
                QB_URL,
                torrent["hash"],
                seeding_time_limit,
                -1,
                dry_run=DRY_RUN,
            ):
                cache_torrent(torrent["hash"], cache)
                updated_count += 1
            print("---")

    if not updated_count:
        print("No torrents updated")


if __name__ == "__main__":
    if SCHEDULE > 0:
        while True:
            main()
            print(f"Waiting for {SCHEDULE} minutes before next run.")
            time.sleep(SCHEDULE * 60)
    else:
        main()
