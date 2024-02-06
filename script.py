import json
import os
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


CACHE_EXPIRY_DAYS = int(os.getenv("CACHE_EXPIRY_DAYS", "14"))
CACHE_FILE = "torrent_cache.json"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ["true", "1", "t"]
SCHEDULE = int(os.getenv("SCHEDULE", "30"))
QB_URL = get_env_variable("QB_URL")
QB_USERNAME = get_env_variable("QB_USERNAME")
QB_PASSWORD = get_env_variable("QB_PASSWORD")
CATEGORY_NAME = get_env_variable("CATEGORY_NAME")
TAG_NAMES = get_env_variable("TAG_NAMES")

session = requests.Session()


def read_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # If there is a JSON decode error, return an empty dictionary
        return {}


def write_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=4)


def is_torrent_cached(torrent_hash, cache):
    """Check if the torrent is in the cache and if the cache is still valid."""
    if torrent_hash in cache:
        cached_time = datetime.fromisoformat(cache[torrent_hash])
        if datetime.now() < cached_time + timedelta(days=CACHE_EXPIRY_DAYS):
            return True
    return False


def cache_torrent(torrent_hash, cache):
    """Cache the torrent with the current timestamp."""
    cache[torrent_hash] = datetime.now().isoformat()
    write_cache(cache)


def qb_login(url, username, password):
    login_url = f"{url}/api/v2/auth/login"
    data = {"username": username, "password": password}
    try:
        response = session.post(login_url, data=data)
        if response.text == "Ok.":
            print("Login successful")
        else:
            print("Login failed")
    except RequestException as e:
        print(f"Error logging in: {e}")


def get_torrents_by_category(url, category_name):
    torrents_url = f"{url}/api/v2/torrents/info"
    params = {"filter": "all", "category": category_name}
    try:
        response = session.get(torrents_url, params=params)
        if response.ok:
            torrents = response.json()
            return torrents
        else:
            print("Could not get torrent list")
            return None
    except RequestException as e:
        print(f"Error retrieving torrents: {e}")
        return None


def get_torrents_by_tag(url, tag_name):
    torrents_url = f"{url}/api/v2/torrents/info"
    params = {"filter": "all", "tag": tag_name}
    try:
        response = session.get(torrents_url, params=params)
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
        return
    try:
        response = session.post(set_limits_url, headers=headers, data=data)
        if response.ok:
            print(f"Seed limits set for torrent {torrent_hash}")
        else:
            print("Failed to set seed limits")
    except RequestException as e:
        print(f"Error setting seed limits: {e}")


def get_time_difference(original_added_on, cross_added_on, seeding_time_limit):
    # convert epoch time to datetime object
    time = datetime.fromtimestamp(original_added_on)

    # add minutes
    new_time = time + timedelta(minutes=seeding_time_limit)

    # calculate the difference
    cross_time = time = datetime.fromtimestamp(cross_added_on)
    time_diff = new_time - cross_time

    # convert the difference to minutes and round it
    minutes_diff = round(time_diff.total_seconds() / 60)

    return -1 if minutes_diff <= 0 else minutes_diff


def main():
    qb_login(QB_URL, QB_USERNAME, QB_PASSWORD)
    cache = read_cache()
    updated = False
    print(f"handling torrents with tags: {TAG_NAMES}")
    for tag_name in TAG_NAMES:
        print(f"handling torrents with tag: {tag_name}")
        cross_seed_torrents = get_torrents_by_tag(QB_URL, tag_name)
        if cross_seed_torrents:
            for torrent in cross_seed_torrents:
                if is_torrent_cached(torrent["hash"], cache):
                    continue
                print(f"Name: {torrent['name']}")
                print(f"State: {torrent['state']}")
                print(f"Hash: {torrent['hash']}")
                print("---")
                original_category = torrent["category"].split(".")[0]
                original_torrents = get_torrents_by_category(
                    QB_URL,
                    original_category,
                )
                for original_torrent in original_torrents:
                    if original_torrent["name"] != torrent["name"]:
                        continue
                    print(f"Found original torrent: {original_torrent['hash']}")
                    seeding_time_limit = get_time_difference(
                        original_torrent["added_on"],
                        torrent["added_on"],
                        original_torrent["seeding_time_limit"],
                    )
                    set_torrent_seed_limits(
                        QB_URL,
                        torrent["hash"],
                        seeding_time_limit,
                        original_torrent.get("ratio_limit", -1),
                        dry_run=DRY_RUN,
                    )
                    cache_torrent(torrent["hash"], cache)
                    updated = True
                    print("---")
        if not updated:
            print("No torrents updated")


if __name__ == "__main__":
    if SCHEDULE > 0:
        while True:
            main()
            print(f"Waiting for {SCHEDULE} minutes before next run.")
            time.sleep(SCHEDULE * 60)
    else:
        main()
