import queue
import sys
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))

from usb_vendor.usb_stream import USBStream  # noqa: E402


class HostRxAckContractTests(unittest.TestCase):
    def _state(self, total: int = 20):
        state = type("AckState", (), {})()
        state._host_rx_ack_stop = False
        state._running = True
        state.host_rx_ack_interval = 0.1
        state.host_rx_ack_write_t = time.time()
        state.host_rx_ack_write_total_frames = int(total)
        state.rx_cnt_ch0 = int(total // 2)
        state.rx_cnt_ch1 = int(total - state.rx_cnt_ch0)
        state._host_rx_ack_q = queue.Queue(maxsize=1)
        return state

    def test_timer_never_repeats_an_unchanged_frame_count(self) -> None:
        state = self._state(20)
        writes = []
        state._write_host_rx_ack = lambda total: writes.append(int(total)) or True
        worker = threading.Thread(target=USBStream._host_rx_ack_loop, args=(state,), daemon=True)
        worker.start()
        time.sleep(0.28)
        state._host_rx_ack_stop = True
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(writes, [])

    def test_timer_coalesces_only_real_parsed_frame_progress(self) -> None:
        state = self._state(20)
        wrote = threading.Event()
        writes = []

        def write_ack(total: int) -> bool:
            writes.append(int(total))
            state.host_rx_ack_write_total_frames = int(total)
            state.host_rx_ack_write_t = time.time()
            wrote.set()
            return True

        state._write_host_rx_ack = write_ack
        worker = threading.Thread(target=USBStream._host_rx_ack_loop, args=(state,), daemon=True)
        worker.start()
        state.rx_cnt_ch0 += 1
        self.assertTrue(wrote.wait(timeout=0.5))
        time.sleep(0.15)
        state._host_rx_ack_stop = True
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(writes, [21])

    def test_production_default_matches_firmware_ack_window(self) -> None:
        source = (ROOT / "host" / "usb_vendor" / "usb_stream.py").read_text(encoding="utf-8")
        engine = (ROOT / "host" / "BMI30.200.py.2026-08-25-1153").read_text(encoding="utf-8")
        self.assertIn("BMI30_HOST_RX_ACK_INTERVAL', '0.25'", source)
        self.assertIn('"BMI30_HOST_RX_ACK_INTERVAL": "0.25"', engine)


if __name__ == "__main__":
    unittest.main()
