import time
import unittest
from unittest import mock

import hotspot_info_server as portal


class GroupUidDeduplicationTests(unittest.TestCase):
    @mock.patch.object(
        portal,
        "_read_core_optic_settings",
        return_value={
            "reaction_enabled": False,
            "neighbor_reaction_enabled": True,
            "reaction_local_active": False,
            "reaction_neighbor_active": True,
        },
    )
    def test_public_group_state_exports_own_device_reaction(self, _settings: mock.Mock) -> None:
        state = portal.collect_public_group_state({
            "events": {"optic_state": {"optic_active": False}},
            "sensors": {"local": {}},
        })

        self.assertFalse(state["optic_active"])
        self.assertFalse(state["reaction_enabled"])
        self.assertTrue(state["neighbor_reaction_enabled"])
        self.assertFalse(state["reaction_local_active"])
        self.assertTrue(state["reaction_neighbor_active"])

        remote = portal._public_group_state_from_status({"group_state": state})
        self.assertEqual(remote, state)

    def test_uid96_is_normalized_to_24_hex_characters(self) -> None:
        self.assertEqual(
            portal._normalize_stm32_uid96("33363534 30325113 00090040"),
            "333635343032511300090040",
        )
        self.assertEqual(portal._normalize_stm32_uid96("ABC"), "")

    def test_stm32_display_id_is_always_compact(self) -> None:
        self.assertEqual(
            portal._short_stm32_display_id("33363534 30325113 00090040"),
            "300090040",
        )
        self.assertEqual(
            portal._short_stm32_display_id(
                {
                    "uid96": "333635343032511300090040",
                    "short_id": "8CC938B79",
                }
            ),
            "8CC938B79",
        )

    def test_stm32_header_identity_uses_compact_id(self) -> None:
        text = portal.format_stm32_identity(
            {
                "uid96_words": "33363534 30325113 00090040",
                "fw_version": "1.2.37",
            }
        )
        self.assertEqual(text, "300090040 / FW 1.2.37")

    def test_transition_snapshot_keeps_current_local_id(self) -> None:
        cache = {
            "updated_at": time.time(),
            "identity": {
                "stm32": {"uid96": "333635343032511300090040"},
            },
            "events": {
                "sensor_map": {
                    "valid": True,
                    "sync_seen_mask": (1 << 5) | (1 << 7),
                    "node_count": 2,
                    "local_node_id": 5,
                    "device_id": 5,
                    "device_id_assigned": True,
                },
            },
            "sensors": {
                "local": {"node_id": 5, "local": True, "online": True},
                "remote": [{"node_id": 7, "seen": True, "online": True}],
            },
            "rs485_ident": {
                "local": {
                    "node_id": 7,
                    "short_id": "8CC938B79",
                    "local": True,
                    "recent": True,
                    "last_ms": 100,
                },
                "nodes": {
                    "7": {
                        "node_id": 7,
                        "short_id": "8CC938B79",
                        "local": True,
                        "recent": True,
                        "last_ms": 100,
                    },
                },
            },
        }

        snapshot = portal._device_cache_sensors(cache)

        self.assertEqual(snapshot["sync"]["sync_seen_mask"], (1 << 5) | (1 << 7))
        self.assertEqual(snapshot["group_seen_mask"], 1 << 5)
        self.assertEqual(snapshot["group_device_ids"], [5])
        self.assertEqual(snapshot["deduplicated_node_ids"], [7])
        self.assertEqual(snapshot["remote"], [])
        self.assertEqual(
            snapshot["local"]["uid_key"],
            "uid96:333635343032511300090040",
        )

    def test_remote_uid_alias_keeps_newest_live_id(self) -> None:
        kept, active_mask, dropped = portal._dedupe_group_identity_nodes(
            {
                4: {"node_id": 4, "short_id": "ABCDEF123", "recent": True, "last_ms": 100},
                12: {"node_id": 12, "short_id": "ABCDEF123", "recent": True, "last_ms": 200},
            },
            (1 << 4) | (1 << 12),
            True,
            -1,
        )

        self.assertEqual(sorted(kept), [12])
        self.assertEqual(active_mask, 1 << 12)
        self.assertEqual(dropped, [4])

    def test_lan_publication_keeps_one_current_uid(self) -> None:
        uid96 = "333635343032511300090040"
        devices = portal._current_group_lan_devices(
            [
                {
                    "node_id": 4,
                    "device_id_assigned": True,
                    "stm32_uid96": uid96,
                    "last_seen_at": 10.0,
                },
                {
                    "node_id": 12,
                    "device_id_assigned": True,
                    "stm32_uid96": uid96,
                    "last_seen_at": 20.0,
                },
            ],
            {"group_seen_mask": (1 << 4) | (1 << 12)},
        )

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["node_id"], 12)
        self.assertEqual(devices[0]["uid_key"], f"uid96:{uid96}")

    def test_public_groups_use_current_event_cache_members(self) -> None:
        now = time.time()
        cache = {
            "updated_at": now,
            "updated_iso": "2026-08-12T14:40:00+0200",
            "source": "bulk_evt1",
            "identity": {"stm32": {"uid96": "333635343032511300090040", "fw_version": "1.2.37"}},
            "sync": {"role": "slave", "device_id": 7, "device_id_assigned": True, "sync_seen_mask": (1 << 7) | (1 << 10)},
            "sensors": {
                "local": {
                    "node_id": 7,
                    "local": True,
                    "online": True,
                    "sensor_updated_iso": "2026-08-12T14:39:59+0200",
                },
                "remote": [
                    {
                        "node_id": 10,
                        "master": True,
                        "seen": True,
                        "online": True,
                        "sensor_updated_iso": "2026-08-12T14:39:58+0200",
                    }
                ],
            },
        }

        groups, error = portal.collect_public_groups(cache)

        self.assertEqual(error, "")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["group_id"], "rs485")
        self.assertEqual(groups[0]["role"], "slave")
        self.assertEqual([member["device_id"] for member in groups[0]["members"]], ["M10", "S07"])
        self.assertTrue(all(member["connected"] for member in groups[0]["members"]))
        self.assertEqual(portal.detect_stm32_firmware_version(cache), "1.2.37")

    def test_public_group_cache_error_is_distinct_from_empty_group(self) -> None:
        groups, error = portal.collect_public_groups({"_stale": True})
        self.assertEqual(groups, [])
        self.assertIn("stale", error.lower())

    def test_public_login_page_is_compact_and_omits_connected_groups(self) -> None:
        data = {
            "hostname": "BMI30-TEST",
            "hotspot": {"ssid": "BMI30", "ip": "10.42.0.1"},
            "access": {"ip": "10.42.0.1", "role": "hotspot"},
            "sync_mode": {"value": "slave", "code": "S07", "source": "event-cache", "device_responded": True},
            "services": {"ssh_user": "techaid", "rdp": 3389, "web_scheme": "http"},
            "generated_at": "2026-08-12 14:40:00",
            "interfaces": [
                {"iface": "lo", "ip": "127.0.0.1", "cidr": "127.0.0.1/8", "role": "loopback"},
                {"iface": "wlan0ap", "ip": "10.42.0.1", "cidr": "10.42.0.1/24", "role": "hotspot"},
                {"iface": "wlan0", "ip": "192.168.0.163", "cidr": "192.168.0.163/24", "role": "wifi"},
            ],
            "logos": {},
            "groups_error": "",
            "groups": [
                {
                    "group_id": "rs485",
                    "name": "RS485 Group (M10)",
                    "role": "slave",
                    "members": [
                        {
                            "device_id": "M10",
                            "name": "RS485 node 10",
                            "role": "master",
                            "connected": True,
                            "last_seen_at": "2026-08-12T14:39:58+0200",
                            "local": False,
                        }
                    ],
                }
            ],
        }

        page = portal.render_html_page(data).decode("utf-8")
        self.assertNotIn("Connected Groups", page)
        self.assertNotIn("RS485 Group (M10)", page)
        self.assertNotIn("connected-groups-card", page)
        self.assertIn("grid-template-columns:repeat(4,minmax(0,1fr))", page)
        self.assertIn("grid-template-columns:max-content minmax(0,1fr)", page)
        self.assertNotIn("<th>Role</th>", page)
        self.assertNotIn("This device:", page)
        self.assertNotIn("127.0.0.1", page)
        self.assertLess(
            page.index('class="is-primary-interface"'),
            page.index('data-label="Type">HotSpot'),
        )
        self.assertIn('action="portal-login"', page)
        self.assertIn('href="api/status"', page)

    def test_redirects_remain_relative_below_hub_mount(self) -> None:
        handler = object.__new__(portal.HotspotInfoHandler)
        handler.request = object()
        handler.headers = {"X-Forwarded-Proto": "https", "Host": "www.teiots.net"}

        handler.path = "/not-found"
        self.assertEqual(
            handler._absolute_url("/login?v=test", scheme="https"),
            "login?v=test",
        )

        handler.path = "/portal-core/api/status"
        self.assertEqual(
            handler._absolute_url("/login?v=test", scheme="https"),
            "../../login?v=test",
        )

    def test_proxy_bootstrap_recognizes_production_hub_prefix(self) -> None:
        bootstrap = portal.render_style_bootstrap()
        self.assertIn("(?:\\/bmi30)?\\/device", bootstrap)


if __name__ == "__main__":
    unittest.main()
