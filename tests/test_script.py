import importlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch


REQUIRED_ENV = {
    "QB_URL": "http://qbittorrent.local",
    "QB_USERNAME": "user",
    "QB_PASSWORD": "pass",
    "CATEGORY_NAME": "unused",
    "TAG_NAMES": "unused",
    "CAT_NAMES": '["cross-seed"]',
    "PARTIAL_MATCH_MAX_EXTRA_BYTES": "100",
}


def load_script():
    os.environ.update(REQUIRED_ENV)
    sys.modules.pop("script", None)
    return importlib.import_module("script")


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_alignment_uses_elapsed_seed_time_for_both_torrents(self):
        source = {
            "seeding_time_limit": 1440,
            "seeding_time": 100 * 60,
        }
        cross_seed = {
            "seeding_time": 5 * 60,
        }

        self.assertEqual(
            self.script.calculate_aligned_seed_time_limit(source, cross_seed),
            1345,
        )

    def test_alignment_rounds_small_positive_remaining_time_up(self):
        source = {
            "seeding_time_limit": 10,
            "seeding_time": (9 * 60) + 50,
        }
        cross_seed = {
            "seeding_time": 0,
        }

        self.assertEqual(
            self.script.calculate_aligned_seed_time_limit(source, cross_seed),
            1,
        )

    def test_alignment_preserves_unlimited_source_limit(self):
        source = {
            "seeding_time_limit": -1,
            "seeding_time": 3600,
        }
        cross_seed = {
            "seeding_time": 0,
        }

        self.assertEqual(
            self.script.calculate_aligned_seed_time_limit(source, cross_seed),
            -1,
        )


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_renamed_cross_seed_matches_source_when_only_small_extra_files_differ(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "CC_(1955)_Song of the Road",
            "size": 1_050,
        }
        source = {
            "hash": "sourcehash",
            "name": "Pather Panchali 1955 1080p Blu-ray AVC LPCM 1.0",
            "size": 1_000,
        }

        def fake_get_files(_url, torrent_hash):
            return {
                "crosshash": [
                    {"name": "feature.mkv", "size": 1_000},
                    {"name": "booklet.pdf", "size": 50},
                ],
                "sourcehash": [
                    {"name": "Pather Panchali.mkv", "size": 1_000},
                ],
            }[torrent_hash]

        with patch.object(self.script, "get_torrent_files", side_effect=fake_get_files):
            match = self.script.find_matching_original_torrent(
                [source],
                cross_seed,
                "http://qbittorrent.local",
            )

        self.assertEqual(match, source)

    def test_file_list_fallback_skips_ambiguous_matches(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "CC_(1955)_Song of the Road",
            "size": 1_050,
        }
        source_a = {
            "hash": "sourcehash-a",
            "name": "Unrelated A",
            "size": 1_000,
        }
        source_b = {
            "hash": "sourcehash-b",
            "name": "Unrelated B",
            "size": 1_000,
        }

        def fake_get_files(_url, torrent_hash):
            return {
                "crosshash": [
                    {"name": "feature.mkv", "size": 1_000},
                    {"name": "booklet.pdf", "size": 50},
                ],
                "sourcehash-a": [
                    {"name": "first.mkv", "size": 1_000},
                ],
                "sourcehash-b": [
                    {"name": "second.mkv", "size": 1_000},
                ],
            }[torrent_hash]

        with (
            patch.object(self.script, "get_torrent_files", side_effect=fake_get_files),
            redirect_stdout(io.StringIO()),
        ):
            match = self.script.find_matching_original_torrent(
                [source_a, source_b],
                cross_seed,
                "http://qbittorrent.local",
            )

        self.assertIsNone(match)

    def test_file_list_fallback_only_fetches_size_window_candidates(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "CC_(1955)_Song of the Road",
            "size": 1_050,
        }
        source_in_window = {
            "hash": "sourcehash",
            "name": "Pather Panchali 1955 1080p Blu-ray AVC LPCM 1.0",
            "size": 1_000,
        }
        source_too_small = {
            "hash": "smallhash",
            "name": "Small Movie",
            "size": 100,
        }
        source_too_large = {
            "hash": "largehash",
            "name": "Large Movie",
            "size": 2_000,
        }
        fetched_hashes = []

        def fake_get_files(_url, torrent_hash):
            fetched_hashes.append(torrent_hash)
            return {
                "crosshash": [
                    {"name": "feature.mkv", "size": 1_000},
                    {"name": "booklet.pdf", "size": 50},
                ],
                "sourcehash": [
                    {"name": "Pather Panchali.mkv", "size": 1_000},
                ],
            }[torrent_hash]

        with patch.object(self.script, "get_torrent_files", side_effect=fake_get_files):
            match = self.script.find_matching_original_torrent(
                [source_too_small, source_in_window, source_too_large],
                cross_seed,
                "http://qbittorrent.local",
            )

        self.assertEqual(match, source_in_window)
        self.assertEqual(fetched_hashes, ["crosshash", "sourcehash"])


class QbittorrentApiTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_set_torrent_seed_limits_returns_true_only_for_successful_update(self):
        response = Mock(ok=True)
        fake_session = Mock()
        fake_session.post.return_value = response

        with (
            patch.object(self.script, "session", fake_session),
            redirect_stdout(io.StringIO()),
        ):
            result = self.script.set_torrent_seed_limits(
                "http://qbittorrent.local",
                "abc123",
                60,
                -1,
            )

        self.assertIs(result, True)

    def test_set_torrent_seed_limits_returns_false_for_dry_run(self):
        fake_session = Mock()

        with (
            patch.object(self.script, "session", fake_session),
            redirect_stdout(io.StringIO()),
        ):
            result = self.script.set_torrent_seed_limits(
                "http://qbittorrent.local",
                "abc123",
                60,
                -1,
                dry_run=True,
            )

        self.assertIs(result, False)
        fake_session.post.assert_not_called()


class MainLoopTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_unhealthy_cross_seed_state_is_not_processed_or_cached(self):
        source = {
            "hash": "sourcehash",
            "name": "Movie.2024.1080p",
            "seeding_time_limit": 60,
            "seeding_time": 600,
            "tags": "",
            "category": "movies",
        }

        for state in ("error", "missingFiles"):
            with self.subTest(state=state):
                cross_seed = {
                    "hash": f"crosshash-{state}",
                    "name": "Movie.2024.1080p",
                    "state": state,
                    "seeding_time": 0,
                }

                with (
                    patch.object(self.script, "qb_login", return_value=True),
                    patch.object(self.script, "read_cache", return_value={}),
                    patch.object(
                        self.script,
                        "get_torrents_by_category",
                        return_value=[cross_seed],
                    ),
                    patch.object(
                        self.script,
                        "get_torrents_excluding_category_and_tag",
                        return_value=[source],
                    ),
                    patch.object(self.script, "set_torrent_seed_limits") as set_limits,
                    patch.object(self.script, "cache_torrent") as cache_torrent,
                    redirect_stdout(io.StringIO()),
                ):
                    self.script.main()

                set_limits.assert_not_called()
                cache_torrent.assert_not_called()

    def test_failed_qb_update_is_not_cached(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "Movie.2024.1080p",
            "state": "uploading",
            "added_on": 1_000,
            "seeding_time": 0,
        }
        source = {
            "hash": "sourcehash",
            "name": "Movie.2024.1080p",
            "completion_on": 500,
            "seeding_time_limit": 60,
            "seeding_time": 600,
            "tags": "",
            "category": "movies",
        }

        with (
            patch.object(self.script, "qb_login", return_value=True),
            patch.object(self.script, "read_cache", return_value={}),
            patch.object(self.script, "get_torrents_by_category", return_value=[cross_seed]),
            patch.object(
                self.script,
                "get_torrents_excluding_category_and_tag",
                return_value=[source],
            ),
            patch.object(self.script, "set_torrent_seed_limits", return_value=False),
            patch.object(self.script, "cache_torrent") as cache_torrent,
            redirect_stdout(io.StringIO()),
        ):
            self.script.main()

        cache_torrent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
