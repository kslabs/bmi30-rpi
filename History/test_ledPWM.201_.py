import sys
import cv2
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QSlider
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt, QTimer
from gpiozero import PWMLED
from picamera2 import Picamera2
from libcamera import controls
import time
import numpy as np
import multiprocessing
from multiprocessing import Queue

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Camera Preview with PyQt5")
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Layout setup
        self.layout = QVBoxLayout()
        self.label = QLabel()
        self.layout.addWidget(self.label)

        # Button to capture image
        self.capture_button = QPushButton("Capture Image")
        self.capture_button.clicked.connect(self.capture_image)
        self.layout.addWidget(self.capture_button)

        # Button to start video
        self.open_camera_button = QPushButton("Open Camera")
        self.open_camera_button.clicked.connect(self.start_video_stream)
        self.layout.addWidget(self.open_camera_button)

        # Create a vertical slider for LED brightness control
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 100)  # Set range of slider (0-100)
        self.slider.setValue(0)  # Set initial value
        self.slider.valueChanged.connect(self.slider_changed)
        self.layout.addWidget(self.slider)

        self.central_widget.setLayout(self.layout)

        # Camera setup
        self.picam = None  # Initialize Picamera2 object
        self.capture_count = 1

        # Queue for communication between processes
        self.frame_queue = Queue()

        # Initialize PWMLED on GPIO pin 12
        self.led = PWMLED(12)

    def update_frame(self, frame):
        if frame is not None:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            self.label.setPixmap(pixmap)

    def start_video_stream(self):
        if self.picam is None:
            self.camera_running = False
            self.video_process = multiprocessing.Process(target=self.video_stream_process, args=(self.frame_queue,))
            self.video_process.daemon = True
            self.video_process.start()

            # Start timer to update GUI
            self.timer = QTimer()
            self.timer.start(100)  # 100ms update interval
            self.timer.timeout.connect(self.update_gui)

    def video_stream_process(self, frame_queue):
        picam = Picamera2()
        picam.preview_configuration.main.size = (1380, 640)
        picam.preview_configuration.main.format = "RGB888"
        picam.preview_configuration.align()
        picam.configure("preview")
        picam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        picam.start()

        while True:
            frame = picam.capture_array()
            frame_queue.put(frame)

    def update_gui(self):
        if not self.frame_queue.empty():
            frame = self.frame_queue.get()
            self.update_frame(frame)

    def stop_video_stream(self):
        if self.picam is not None:
            self.picam.close()
            self.picam = None

    def capture_image(self):
        if self.picam is not None:
            a = self.capture_picamera_image()
            self.display_captured_image(a)

    def capture_picamera_image(self):
        request = self.picam.capture_request()
        self.file_name = f"captured_image_{self.capture_count}.jpg"  # Construct file name with counter
        request.save("main", self.file_name)
        print(f"Image captured: {self.file_name}")
        request.release()
        print(self.capture_count)
        self.capture_count += 1
        print(self.capture_count)
        return self.file_name

    def display_captured_image(self, a):
        image = QPixmap(f"{a}")  # Corrected
        self.label.setPixmap(image.scaled(1380, 640))  # Resize if necessary

    def slider_changed(self, value):
        brightness = value / 100.0
        self.led.value = brightness

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())