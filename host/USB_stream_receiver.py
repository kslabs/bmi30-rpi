#!/usr/bin/env python3
"""
USB Stream Receiver for BMI30 Streamer
Receives 2048-byte synchronized buffers from STM32 and displays on oscilloscope
"""

import usb.core
import usb.util
import struct
import time
import numpy as np
from collections import deque
import sys
import threading
from queue import Queue

# PyQtGraph for display
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

# ===== Constants =====
STREAM_SAMPLES_PER_CHANNEL = 1000
STREAM_CHANNELS = 2
STREAM_PACKET_SIZE = 2048  # Header(6) + Data(2042)

VID, PID = 0xCAFE, 0x4001
ENDPOINT_IN = 0x81  # Bulk IN endpoint

# CRC16-CCITT
def crc16_ccitt(data, crc=0xFFFF):
    """Compute CRC16-CCITT checksum"""
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc

# ===== USB Communication =====
class StreamReceiver:
    def __init__(self):
        self.dev = None
        self.stats = {
            'packets_received': 0,
            'packets_valid': 0,
            'packets_crc_error': 0,
            'total_bytes': 0,
            'start_time': None,
            'throughput_mbps': 0.0,
            'last_id': -1,
            'dropped_packets': 0,
        }
        self.queue = Queue(maxsize=10)
        self.running = False
        
    def connect(self):
        """Connect to USB device"""
        self.dev = usb.core.find(find_all=False, idVendor=VID, idProduct=PID)
        if not self.dev:
            raise RuntimeError(f"Device not found (VID={VID:04X}, PID={PID:04X})")
        
        print(f"✓ Device found: {self.dev}")
        
        # Set configuration
        self.dev.set_configuration()
        print("✓ Configuration set")
        
        # Clear any pending data
        time.sleep(0.1)
        
    def start_stream(self, freq_hz=50):
        """Send START command to device"""
        # Implement vendor command to start streaming
        # This would typically be a VENDOR_IN or VENDOR_OUT request
        print(f"→ Starting stream at {freq_hz} Hz...")
        
    def stop_stream(self):
        """Send STOP command to device"""
        print("→ Stopping stream...")
        
    def read_loop(self):
        """Main read loop (runs in thread)"""
        while self.running:
            try:
                # Read packet from device
                data = self.dev.read(ENDPOINT_IN, STREAM_PACKET_SIZE, timeout=2000)
                
                if len(data) < 6:
                    print(f"⚠ Packet too short: {len(data)} bytes")
                    continue
                
                # Parse header
                buffer_id = struct.unpack_from('<I', data, 0)[0]
                crc_received = struct.unpack_from('<H', data, 4)[0]
                
                # Compute CRC (with CRC field = 0)
                data_for_crc = bytearray(data)
                struct.pack_into('<H', data_for_crc, 4, 0)
                crc_computed = crc16_ccitt(data_for_crc)
                
                self.stats['packets_received'] += 1
                self.stats['total_bytes'] += len(data)
                
                if crc_received != crc_computed:
                    self.stats['packets_crc_error'] += 1
                    print(f"✗ CRC Error: ID={buffer_id} Expected={crc_computed:04X} Got={crc_received:04X}")
                    continue
                
                # Check for dropped packets
                if self.stats['last_id'] >= 0:
                    expected_id = (self.stats['last_id'] + 1) & 0xFFFFFFFF
                    if buffer_id != expected_id:
                        dropped = (buffer_id - expected_id) & 0xFFFFFFFF
                        self.stats['dropped_packets'] += dropped
                        print(f"⚠ Dropped {dropped} packets (ID {expected_id} -> {buffer_id})")
                
                self.stats['last_id'] = buffer_id
                self.stats['packets_valid'] += 1
                
                # Parse ADC data
                adc1 = np.zeros(STREAM_SAMPLES_PER_CHANNEL, dtype=np.uint16)
                adc2 = np.zeros(STREAM_SAMPLES_PER_CHANNEL, dtype=np.uint16)
                
                offset = 6
                for i in range(STREAM_SAMPLES_PER_CHANNEL):
                    adc1[i] = struct.unpack_from('<H', data, offset + i*4)[0]
                    adc2[i] = struct.unpack_from('<H', data, offset + i*4 + 2)[0]
                
                # Put in queue for display
                try:
                    self.queue.put_nowait({
                        'id': buffer_id,
                        'adc1': adc1,
                        'adc2': adc2,
                        'timestamp': time.time()
                    })
                except:
                    pass  # Queue full, drop oldest
                
                # Update throughput
                if self.stats['start_time'] is None:
                    self.stats['start_time'] = time.time()
                
                elapsed = time.time() - self.stats['start_time']
                if elapsed > 1.0:
                    throughput_bits = self.stats['total_bytes'] * 8
                    self.stats['throughput_mbps'] = throughput_bits / (elapsed * 1_000_000)
                    
            except usb.core.USBTimeoutError:
                pass
            except Exception as e:
                print(f"✗ Read error: {e}")
                break

# ===== PyQtGraph Display =====
class OscilloscopeWindow(QtWidgets.QMainWindow):
    def __init__(self, receiver):
        super().__init__()
        self.receiver = receiver
        self.setWindowTitle("BMI30 Stream Oscilloscope")
        self.setGeometry(100, 100, 1200, 700)
        
        # Create widgets
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # Plot area
        self.plot = pg.PlotWidget(title="ADC Waveforms")
        self.plot.setLabel('bottom', 'Sample')
        self.plot.setLabel('left', 'ADC Value (0-4095)')
        self.plot.setYRange(0, 4095)
        layout.addWidget(self.plot)
        
        # Legend
        self.plot.addLegend()
        
        # Curves
        self.curve_adc1 = self.plot.plot(pen=pg.mkPen('red', width=2), name='ADC1')
        self.curve_adc2 = self.plot.plot(pen=pg.mkPen('blue', width=2), name='ADC2')
        
        # Status area
        status_layout = QtWidgets.QHBoxLayout()
        
        self.label_stats = QtWidgets.QLabel()
        status_layout.addWidget(self.label_stats)
        
        btn_layout = QtWidgets.QVBoxLayout()
        
        self.btn_start = QtWidgets.QPushButton("Start Stream")
        self.btn_start.clicked.connect(self.on_start)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QtWidgets.QPushButton("Stop Stream")
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)
        
        status_layout.addLayout(btn_layout)
        layout.addLayout(status_layout)
        
        # Timer for updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.start(50)  # 20 Hz update
        
    def on_start(self):
        self.receiver.running = True
        self.receiver.start_stream(freq_hz=50)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        # Start read thread
        self.read_thread = threading.Thread(target=self.receiver.read_loop, daemon=True)
        self.read_thread.start()
        
    def on_stop(self):
        self.receiver.running = False
        self.receiver.stop_stream()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        
    def update_display(self):
        try:
            # Get latest packet from queue
            packet = self.receiver.queue.get_nowait()
            
            # Update curves
            x = np.arange(len(packet['adc1']))
            self.curve_adc1.setData(x, packet['adc1'])
            self.curve_adc2.setData(x, packet['adc2'])
            
            # Update stats
            stats = self.receiver.stats
            status_text = (
                f"RX: {stats['packets_received']} | "
                f"Valid: {stats['packets_valid']} | "
                f"CRC Err: {stats['packets_crc_error']} | "
                f"Dropped: {stats['dropped_packets']} | "
                f"Throughput: {stats['throughput_mbps']:.2f} Mbps"
            )
            self.label_stats.setText(status_text)
            
        except:
            # No new packet available
            pass

# ===== Main =====
def main():
    print("BMI30 Stream Receiver v1.0")
    print("=" * 60)
    
    # Create receiver
    receiver = StreamReceiver()
    
    try:
        print("→ Connecting to device...")
        receiver.connect()
        print("✓ Connected!")
        
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return 1
    
    # Create and show GUI
    app = QtWidgets.QApplication(sys.argv)
    window = OscilloscopeWindow(receiver)
    window.show()
    
    return app.exec_()

if __name__ == '__main__':
    sys.exit(main())
