import importlib
import io
import logging
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


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_configure_logging_formats_human_readable_stdout(self):
        root_logger = logging.getLogger()
        old_handlers = root_logger.handlers[:]
        old_level = root_logger.level
        stream = io.StringIO()

        try:
            self.script.configure_logging(stream=stream)
            self.script.logger.info("Traceable event hash=%s", "abc123")
        finally:
            root_logger.handlers[:] = old_handlers
            root_logger.setLevel(old_level)

        self.assertRegex(
            stream.getvalue(),
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
            + r"INFO autoratiorr Traceable event hash=abc123\n$",
        )


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

    def test_alignment_resolves_inherited_unlimited_and_zero_limits(self):
        for max_limit, cross_elapsed, expected in ((-1, 180, -1), (0, 0, 0), (0, 180, 3)):
            with self.subTest(max_limit=max_limit, cross_elapsed=cross_elapsed):
                source = {
                    "seeding_time_limit": -2,
                    "max_seeding_time": max_limit,
                    "seeding_time": 0,
                }
                cross_seed = {"seeding_time": cross_elapsed}
                self.assertEqual(
                    self.script.calculate_aligned_seed_time_limit(source, cross_seed),
                    expected,
                )

    def test_alignment_preserves_default_when_effective_limit_is_unavailable(self):
        self.assertEqual(
            self.script.calculate_aligned_seed_time_limit(
                {"seeding_time_limit": -2}, {"seeding_time": 180}
            ),
            -2,
        )

    def test_alignment_uses_qbit_global_seed_limit_minutes(self):
        source = {
            "seeding_time_limit": -2,
            "max_seeding_time": 14400,
            "seeding_time": 60 * 60,
        }
        cross_seed = {
            "seeding_time": 30 * 60,
        }

        self.assertEqual(
            self.script.calculate_aligned_seed_time_limit(source, cross_seed),
            14370,
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

    def test_renamed_cross_seed_matches_when_source_has_small_extra_files(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "Tracker.Release",
            "size": 1_000,
        }
        source = {
            "hash": "sourcehash",
            "name": "Original.Release",
            "size": 1_050,
        }
        files = {
            "crosshash": [{"name": "renamed.mkv", "size": 1_000}],
            "sourcehash": [
                {"name": "feature.mkv", "size": 1_000},
                {"name": "release.nfo", "size": 50},
            ],
        }

        with patch.object(
            self.script,
            "get_torrent_files",
            side_effect=lambda _url, torrent_hash: files[torrent_hash],
        ):
            match = self.script.find_matching_original_torrent(
                [source], cross_seed, "http://qbittorrent.local"
            )

        self.assertEqual(match, source)

    def test_renamed_cross_seed_matches_when_both_have_different_small_extras(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "Tracker.Release",
            "size": 1_040,
        }
        source = {
            "hash": "sourcehash",
            "name": "Original.Release",
            "size": 1_030,
        }
        files = {
            "crosshash": [
                {"name": "renamed.mkv", "size": 1_000},
                {"name": "tracker.nfo", "size": 40},
            ],
            "sourcehash": [
                {"name": "feature.mkv", "size": 1_000},
                {"name": "release.nfo", "size": 30},
            ],
        }

        with patch.object(
            self.script,
            "get_torrent_files",
            side_effect=lambda _url, torrent_hash: files[torrent_hash],
        ):
            match = self.script.find_matching_original_torrent(
                [source], cross_seed, "http://qbittorrent.local"
            )

        self.assertEqual(match, source)

    def test_file_match_requires_shared_content_and_limits_extras_on_both_sides(self):
        cases = [
            (
                "different content with identical total size",
                [{"size": 1_000}],
                [{"size": 600}, {"size": 400}],
            ),
            (
                "too many unmatched bytes in source",
                [{"size": 1_000}, {"size": 101}],
                [{"size": 1_000}],
            ),
            (
                "too many unmatched bytes in cross seed",
                [{"size": 1_000}],
                [{"size": 1_000}, {"size": 101}],
            ),
            (
                "repeated sizes need separate matches",
                [{"size": 1_000}, {"size": 1_000}],
                [{"size": 1_000}],
            ),
            (
                "a shared small file cannot identify different main content",
                [{"size": 60}, {"size": 1}],
                [{"size": 70}, {"size": 1}],
            ),
            ("empty file lists", [], []),
            ("only empty files", [{"size": 0}], [{"size": 0}]),
            ("missing sizes", [{}], [{}]),
        ]
        for description, source_files, cross_seed_files in cases:
            with self.subTest(description=description):
                self.assertFalse(
                    self.script.matches_source_files_with_small_extras(
                        source_files, cross_seed_files
                    )
                )

    def test_file_list_fallback_logs_when_no_size_candidates_exist(self):
        source = {"hash": "sourcehash", "name": "Original.Release", "size": 2_000}
        cross_seed = {"hash": "crosshash", "name": "Tracker.Release", "size": 1_000}

        with (
            patch.object(self.script, "get_torrent_files") as get_files,
            self.assertLogs("autoratiorr", level="INFO") as logs,
        ):
            match = self.script.find_matching_original_torrent(
                [source], cross_seed, "http://qbittorrent.local"
            )

        self.assertIsNone(match)
        get_files.assert_not_called()
        log_output = "\n".join(logs.output)
        self.assertIn("reason=no_size_candidates", log_output)
        self.assertIn("cross_seed_hash=crosshash", log_output)
        self.assertIn("source_count=1", log_output)
        self.assertIn("cross_seed_size=1000", log_output)
        self.assertIn("max_extra_bytes=100", log_output)

    def test_file_list_fallback_logs_when_file_lists_do_not_match(self):
        source = {"hash": "sourcehash", "name": "Original.Release", "size": 1_000}
        cross_seed = {"hash": "crosshash", "name": "Tracker.Release", "size": 1_000}
        files = {
            "crosshash": [{"name": "different.mkv", "size": 1_000}],
            "sourcehash": [
                {"name": "part1.mkv", "size": 600},
                {"name": "part2.mkv", "size": 400},
            ],
        }

        with (
            patch.object(
                self.script,
                "get_torrent_files",
                side_effect=lambda _url, torrent_hash: files[torrent_hash],
            ),
            self.assertLogs("autoratiorr", level="INFO") as logs,
        ):
            match = self.script.find_matching_original_torrent(
                [source], cross_seed, "http://qbittorrent.local"
            )

        self.assertIsNone(match)
        log_output = "\n".join(logs.output)
        self.assertIn("reason=no_file_match", log_output)
        self.assertIn("size_candidates=1", log_output)
        self.assertIn("unavailable_file_lists=0", log_output)

    def test_file_list_fallback_logs_unavailable_cross_seed_files(self):
        source = {"hash": "sourcehash", "name": "Original.Release", "size": 1_000}
        cross_seed = {"hash": "crosshash", "name": "Tracker.Release", "size": 1_000}

        with (
            patch.object(self.script, "get_torrent_files", return_value=None),
            self.assertLogs("autoratiorr", level="INFO") as logs,
        ):
            match = self.script.find_matching_original_torrent(
                [source], cross_seed, "http://qbittorrent.local"
            )

        self.assertIsNone(match)
        self.assertIn("reason=cross_seed_files_unavailable", "\n".join(logs.output))

    def test_file_list_fallback_logs_unavailable_source_files(self):
        source = {"hash": "sourcehash", "name": "Original.Release", "size": 1_000}
        cross_seed = {"hash": "crosshash", "name": "Tracker.Release", "size": 1_000}

        with (
            patch.object(
                self.script,
                "get_torrent_files",
                side_effect=[[{"size": 1_000}], None],
            ),
            self.assertLogs("autoratiorr", level="INFO") as logs,
        ):
            match = self.script.find_matching_original_torrent(
                [source], cross_seed, "http://qbittorrent.local"
            )

        self.assertIsNone(match)
        log_output = "\n".join(logs.output)
        self.assertIn("reason=no_file_match", log_output)
        self.assertIn("unavailable_file_lists=1", log_output)

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

    def test_login_accepts_legacy_ok_response(self):
        fake_session = Mock()
        fake_session.post.return_value = Mock(status_code=200, text="Ok.\n")

        with patch.object(self.script, "session", fake_session):
            result = self.script.qb_login("http://qbittorrent.local", "user", "pass")

        self.assertIs(result, True)
        fake_session.post.assert_called_once_with(
            "http://qbittorrent.local/api/v2/auth/login",
            data={"username": "user", "password": "pass"},
            timeout=self.script.REQUEST_TIMEOUT,
        )

    def test_login_accepts_qbit_5_2_no_content_response(self):
        fake_session = Mock()
        fake_session.post.return_value = Mock(status_code=204, text="")

        with patch.object(self.script, "session", fake_session):
            result = self.script.qb_login("http://qbittorrent.local", "user", "pass")

        self.assertIs(result, True)

    def test_login_rejects_failed_or_unexpected_responses(self):
        for status_code, text in (
            (200, "Fails."),
            (200, ""),
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (500, "Ok."),
        ):
            with self.subTest(status_code=status_code, text=text):
                fake_session = Mock()
                fake_session.post.return_value = Mock(status_code=status_code, text=text)

                with patch.object(self.script, "session", fake_session):
                    result = self.script.qb_login(
                        "http://qbittorrent.local", "user", "pass"
                    )

                self.assertIs(result, False)

    def test_login_returns_false_for_read_timeout(self):
        fake_session = Mock()
        fake_session.post.side_effect = self.script.requests.exceptions.ReadTimeout()

        with patch.object(self.script, "session", fake_session):
            result = self.script.qb_login("http://qbittorrent.local", "user", "pass")

        self.assertIs(result, False)

    def test_source_query_excludes_cross_seed_subcategories_and_tags(self):
        torrents = [
            {"hash": "root", "category": "cross-seed", "tags": ""},
            {"hash": "child", "category": "cross-seed/link", "tags": ""},
            {"hash": "nested", "category": "cross-seed/link/child", "tags": ""},
            {"hash": "tagged", "category": "movies", "tags": "other, cross-seed"},
            {"hash": "source", "category": "movies", "tags": "other"},
            {"hash": "similar-prefix", "category": "cross-seed-other", "tags": ""},
            {"hash": "uncategorized", "category": "", "tags": ""},
        ]
        fake_session = Mock()
        fake_session.get.return_value = Mock(ok=True)
        fake_session.get.return_value.json.return_value = torrents

        with patch.object(self.script, "session", fake_session):
            result = self.script.get_torrents_excluding_category_and_tag(
                "http://qbittorrent.local", "cross-seed", "cross-seed"
            )

        self.assertEqual(
            [torrent["hash"] for torrent in result],
            ["source", "similar-prefix", "uncategorized"],
        )
        fake_session.get.assert_called_once_with(
            "http://qbittorrent.local/api/v2/torrents/info",
            params={"filter": "all"},
            timeout=self.script.REQUEST_TIMEOUT,
        )

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

    def test_set_torrent_seed_limits_satisfies_qbit_5_2_required_parameters(self):
        # Mirrors requireParams() in qBittorrent release-5.2.3's
        # src/webui/api/torrentscontroller.cpp::setShareLimitsAction().
        required = {
            "hashes",
            "ratioLimit",
            "seedingTimeLimit",
            "inactiveSeedingTimeLimit",
            "shareLimitAction",
        }

        def validate_request(_url, **kwargs):
            missing = required - kwargs["data"].keys()
            return Mock(ok=not missing, status_code=400 if missing else 200)

        fake_session = Mock()
        fake_session.post.side_effect = validate_request
        with patch.object(self.script, "session", fake_session):
            result = self.script.set_torrent_seed_limits(
                "http://qbittorrent.local", "abc123", 5742, -1
            )

        self.assertIs(result, True)
        self.assertEqual(
            fake_session.post.call_args.kwargs["data"],
            {
                "hashes": "abc123",
                "seedingTimeLimit": 5742,
                "ratioLimit": -1,
                "inactiveSeedingTimeLimit": -1,
                "shareLimitAction": "Default",
            },
        )

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

    def test_main_logs_cross_seed_context_for_successful_update(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "Movie.2024.1080p",
            "state": "uploading",
            "seeding_time": 0,
            "share_limit_action": "Stop",
        }
        fake_session = Mock()
        fake_session.post.return_value = Mock(ok=True)
        source = {
            "hash": "sourcehash",
            "name": "Movie.2024.1080p",
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
            patch.object(self.script, "session", fake_session),
            patch.object(self.script, "cache_torrent"),
            self.assertLogs("autoratiorr", level="INFO") as logs,
        ):
            self.script.main()

        self.assertEqual(
            fake_session.post.call_args.kwargs["data"]["shareLimitAction"],
            "Stop",
        )
        log_output = "\n".join(logs.output)
        self.assertIn(
            "Processing cross-seed torrent category=cross-seed "
            + "name='Movie.2024.1080p' hash=crosshash state=uploading",
            log_output,
        )
        self.assertIn(
            "Calculated seed limit cross_seed_hash=crosshash "
            + "source_hash=sourcehash seed_limit_minutes=50",
            log_output,
        )

    def test_main_aligns_linked_cross_seed_when_source_has_small_extra_files(self):
        for state in ("stoppedUP", "stalledUP"):
            with self.subTest(state=state):
                cross_seed = {
                    "hash": "crosshash",
                    "name": "Tracker.Release",
                    "state": state,
                    "category": "cross-seed-link",
                    "tags": "cross-seed",
                    "size": 1_000,
                    "seeding_time": 0,
                }
                source = {
                    "hash": "sourcehash",
                    "name": "Original.Release",
                    "category": "movies",
                    "tags": "",
                    "size": 1_050,
                    "seeding_time_limit": 60,
                    "seeding_time": 600,
                }

                def fake_get(url, *, params, timeout):
                    if url.endswith("/torrents/files"):
                        payload = {
                            "crosshash": [{"name": "renamed.mkv", "size": 1_000}],
                            "sourcehash": [
                                {"name": "feature.mkv", "size": 1_000},
                                {"name": "release.nfo", "size": 50},
                            ],
                        }[params["hash"]]
                    elif params.get("category") == "cross-seed-link":
                        payload = [cross_seed]
                    else:
                        payload = [cross_seed, source]
                    return Mock(ok=True, json=Mock(return_value=payload))

                fake_session = Mock()
                fake_session.get.side_effect = fake_get
                fake_session.post.return_value = Mock(ok=True, status_code=204)
                with (
                    patch.object(self.script, "CAT_NAMES", ["cross-seed-link"]),
                    patch.object(self.script, "DRY_RUN", False),
                    patch.object(self.script, "session", fake_session),
                    patch.object(self.script, "read_cache", return_value={}),
                    patch.object(self.script, "cache_torrent") as cache_torrent,
                    self.assertLogs("autoratiorr", level="INFO") as logs,
                ):
                    self.script.main()

                self.assertEqual(fake_session.post.call_count, 2)
                request = fake_session.post.call_args
                self.assertTrue(request.args[0].endswith("/torrents/setShareLimits"))
                self.assertEqual(request.kwargs["data"]["hashes"], "crosshash")
                self.assertEqual(request.kwargs["data"]["seedingTimeLimit"], 50)
                cache_torrent.assert_called_once_with("crosshash", {})
                self.assertIn(
                    "total_torrents=2 eligible_sources=1", "\n".join(logs.output)
                )
                self.assertNotIn("No matching source torrent", "\n".join(logs.output))

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

    def test_whisparr_source_with_zero_seeding_time_is_not_aligned(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "Movie.2024.1080p",
            "state": "uploading",
            "seeding_time": 0,
        }
        source = {
            "hash": "sourcehash",
            "name": "Movie.2024.1080p",
            "seeding_time_limit": 0,
            "seeding_time": 0,
            "tags": "",
            "category": "whisparr",
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
            patch.object(self.script, "set_torrent_seed_limits") as set_limits,
            patch.object(self.script, "cache_torrent") as cache_torrent,
            redirect_stdout(io.StringIO()),
        ):
            self.script.main()

        set_limits.assert_not_called()
        cache_torrent.assert_not_called()

    def test_whisparr_source_with_other_tag_is_not_aligned(self):
        cross_seed = {
            "hash": "crosshash",
            "name": "Movie.2024.1080p",
            "state": "uploading",
            "seeding_time": 0,
        }
        source = {
            "hash": "sourcehash",
            "name": "Movie.2024.1080p",
            "seeding_time_limit": 60,
            "seeding_time": 600,
            "tags": "other",
            "category": "whisparr",
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
            patch.object(self.script, "set_torrent_seed_limits") as set_limits,
            patch.object(self.script, "cache_torrent") as cache_torrent,
            redirect_stdout(io.StringIO()),
        ):
            self.script.main()

        set_limits.assert_not_called()
        cache_torrent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
