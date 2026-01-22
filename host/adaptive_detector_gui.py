"""
GUI панель для адаптивного детектора в реальном времени
Интегрируется в BMI30.200.py
"""

from PyQt5 import QtWidgets, QtCore, QtGui
import time


class AdaptiveDetectorPanel(QtWidgets.QGroupBox):
    """Панель управления адаптивным детектором"""
    
    # Сигналы
    calibration_requested = QtCore.pyqtSignal(int)  # длительность калибровки в секундах
    buffer_test_requested = QtCore.pyqtSignal()
    feedback_signal = QtCore.pyqtSignal(str)  # 'marker', 'noise', 'false_positive'
    
    def __init__(self, detector, parent=None):
        super().__init__("🤖 Адаптивный детектор", parent)
        self.detector = detector
        self.init_ui()
        
        # Таймер для обновления статистики
        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.update_stats_display)
        self.update_timer.start(1000)  # каждую секунду
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # === Секция 1: Калибровка шума ===
        calib_group = QtWidgets.QGroupBox("1️⃣ Калибровка шума")
        calib_layout = QtWidgets.QVBoxLayout()
        
        calib_info = QtWidgets.QLabel(
            "Уберите все метки и запустите калибровку.\n"
            "Система изучит фоновый шум за 1-5 минут."
        )
        calib_info.setWordWrap(True)
        calib_layout.addWidget(calib_info)
        
        calib_controls = QtWidgets.QHBoxLayout()
        
        self.calib_duration_spin = QtWidgets.QSpinBox()
        self.calib_duration_spin.setRange(30, 600)
        self.calib_duration_spin.setValue(120)
        self.calib_duration_spin.setSuffix(" сек")
        calib_controls.addWidget(QtWidgets.QLabel("Длительность:"))
        calib_controls.addWidget(self.calib_duration_spin)
        
        self.btn_start_calib = QtWidgets.QPushButton("▶ Запустить")
        self.btn_start_calib.clicked.connect(self.start_calibration)
        self.btn_start_calib.setStyleSheet("background-color: #4CAF50; color: white;")
        calib_controls.addWidget(self.btn_start_calib)
        
        self.btn_stop_calib = QtWidgets.QPushButton("⏹ Остановить")
        self.btn_stop_calib.clicked.connect(self.stop_calibration)
        self.btn_stop_calib.setEnabled(False)
        calib_controls.addWidget(self.btn_stop_calib)
        
        calib_layout.addLayout(calib_controls)
        
        # Прогресс калибровки
        self.calib_progress = QtWidgets.QProgressBar()
        self.calib_progress.setRange(0, 100)
        calib_layout.addWidget(self.calib_progress)
        
        self.calib_status = QtWidgets.QLabel("Ожидание...")
        calib_layout.addWidget(self.calib_status)
        
        calib_group.setLayout(calib_layout)
        layout.addWidget(calib_group)
        
        # === Секция 2: Тестирование буферов ===
        buffer_group = QtWidgets.QGroupBox("2️⃣ Оптимизация буферов")
        buffer_layout = QtWidgets.QVBoxLayout()
        
        buffer_info = QtWidgets.QLabel(
            "Автоматически найти оптимальное количество буферов (8-64).\n"
            "Периодически подносите и убирайте метку во время теста."
        )
        buffer_info.setWordWrap(True)
        buffer_layout.addWidget(buffer_info)
        
        buffer_controls = QtWidgets.QHBoxLayout()
        
        self.buffer_test_duration = QtWidgets.QSpinBox()
        self.buffer_test_duration.setRange(60, 1800)
        self.buffer_test_duration.setValue(300)
        self.buffer_test_duration.setSuffix(" сек")
        buffer_controls.addWidget(QtWidgets.QLabel("Длительность:"))
        buffer_controls.addWidget(self.buffer_test_duration)
        
        self.btn_buffer_test = QtWidgets.QPushButton("🧪 Тестировать")
        self.btn_buffer_test.clicked.connect(self.start_buffer_test)
        buffer_controls.addWidget(self.btn_buffer_test)
        
        buffer_layout.addLayout(buffer_controls)
        
        self.buffer_status = QtWidgets.QLabel("Текущие буферы: 64")
        buffer_layout.addWidget(self.buffer_status)
        
        buffer_group.setLayout(buffer_layout)
        layout.addWidget(buffer_group)
        
        # === Секция 3: Обратная связь ===
        feedback_group = QtWidgets.QGroupBox("3️⃣ Обратная связь")
        feedback_layout = QtWidgets.QVBoxLayout()
        
        feedback_info = QtWidgets.QLabel(
            "Помогите системе обучаться - отмечайте правильные и ложные срабатывания:"
        )
        feedback_info.setWordWrap(True)
        feedback_layout.addWidget(feedback_info)
        
        feedback_buttons = QtWidgets.QHBoxLayout()
        
        self.btn_confirm_marker = QtWidgets.QPushButton("✓ Правильно")
        self.btn_confirm_marker.clicked.connect(lambda: self.send_feedback('marker'))
        self.btn_confirm_marker.setStyleSheet("background-color: #4CAF50; color: white;")
        feedback_buttons.addWidget(self.btn_confirm_marker)
        
        self.btn_false_positive = QtWidgets.QPushButton("✗ Ложное")
        self.btn_false_positive.clicked.connect(lambda: self.send_feedback('false_positive'))
        self.btn_false_positive.setStyleSheet("background-color: #f44336; color: white;")
        feedback_buttons.addWidget(self.btn_false_positive)
        
        self.btn_missed_marker = QtWidgets.QPushButton("⊘ Пропущено")
        self.btn_missed_marker.clicked.connect(lambda: self.send_feedback('missed'))
        self.btn_missed_marker.setStyleSheet("background-color: #FF9800; color: white;")
        feedback_buttons.addWidget(self.btn_missed_marker)
        
        feedback_layout.addLayout(feedback_buttons)
        
        feedback_group.setLayout(feedback_layout)
        layout.addWidget(feedback_group)
        
        # === Секция 4: Статистика ===
        stats_group = QtWidgets.QGroupBox("📊 Статистика работы")
        stats_layout = QtWidgets.QFormLayout()
        
        self.label_frames_total = QtWidgets.QLabel("0")
        self.label_noise_frames = QtWidgets.QLabel("0")
        self.label_marker_frames = QtWidgets.QLabel("0")
        self.label_false_positives = QtWidgets.QLabel("0")
        self.label_current_buffers = QtWidgets.QLabel("64")
        self.label_optimal_buffers = QtWidgets.QLabel("?")
        self.label_detection_speed = QtWidgets.QLabel("0 мс")
        self.label_threshold_ch0 = QtWidgets.QLabel("?")
        self.label_threshold_ch1 = QtWidgets.QLabel("?")
        self.label_noise_level = QtWidgets.QLabel("?")
        
        stats_layout.addRow("Всего фреймов:", self.label_frames_total)
        stats_layout.addRow("Шум / Метки:", 
                           QtWidgets.QLabel("").setParent(
                               QtWidgets.QWidget()  # placeholder
                           ) or self._create_dual_label(self.label_noise_frames, self.label_marker_frames))
        stats_layout.addRow("Ложные срабатывания:", self.label_false_positives)
        stats_layout.addRow("Текущие буферы:", self.label_current_buffers)
        stats_layout.addRow("Оптимальные буферы:", self.label_optimal_buffers)
        stats_layout.addRow("Скорость детекции:", self.label_detection_speed)
        stats_layout.addRow("Порог CH0:", self.label_threshold_ch0)
        stats_layout.addRow("Порог CH1:", self.label_threshold_ch1)
        stats_layout.addRow("Уровень шума:", self.label_noise_level)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # === Секция 5: Управление данными ===
        data_group = QtWidgets.QGroupBox("💾 Управление накопленными данными")
        data_layout = QtWidgets.QVBoxLayout()
        
        data_info = QtWidgets.QLabel(
            "Данные автоматически сохраняются каждый час.\n"
            "При перезагрузке данные восстанавливаются автоматически."
        )
        data_info.setWordWrap(True)
        data_layout.addWidget(data_info)
        
        self.label_data_age = QtWidgets.QLabel("Данные: нет сохраненных данных")
        data_layout.addWidget(self.label_data_age)
        
        data_buttons = QtWidgets.QHBoxLayout()
        
        self.btn_save_now = QtWidgets.QPushButton("💾 Сохранить сейчас")
        self.btn_save_now.clicked.connect(self.save_data_now)
        self.btn_save_now.setToolTip("Немедленно сохранить накопленные данные")
        data_buttons.addWidget(self.btn_save_now)
        
        self.btn_reset_data = QtWidgets.QPushButton("🔄 Сбросить данные")
        self.btn_reset_data.clicked.connect(self.reset_all_data)
        self.btn_reset_data.setStyleSheet("background-color: #f44336; color: white;")
        self.btn_reset_data.setToolTip("Удалить все накопленные данные и начать заново")
        data_buttons.addWidget(self.btn_reset_data)
        
        data_layout.addLayout(data_buttons)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # === Кнопки сохранения/загрузки (legacy) ===
        save_load_layout = QtWidgets.QHBoxLayout()
        
        self.btn_save_calib = QtWidgets.QPushButton("💾 Сохранить калибровку")
        self.btn_save_calib.clicked.connect(self.save_calibration)
        save_load_layout.addWidget(self.btn_save_calib)
        
        self.btn_load_calib = QtWidgets.QPushButton("📁 Загрузить калибровку")
        self.btn_load_calib.clicked.connect(self.load_calibration)
        save_load_layout.addWidget(self.btn_load_calib)
        
        layout.addLayout(save_load_layout)
        
        layout.addStretch()
    
    def _create_dual_label(self, label1, label2):
        """Создать виджет с двумя метками через /"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label1)
        layout.addWidget(QtWidgets.QLabel("/"))
        layout.addWidget(label2)
        layout.addStretch()
        return widget
    
    def start_calibration(self):
        """Запустить калибровку шума"""
        duration = self.calib_duration_spin.value()
        self.calibration_requested.emit(duration)
        
        self.btn_start_calib.setEnabled(False)
        self.btn_stop_calib.setEnabled(True)
        self.calib_status.setText(f"⏳ Калибровка... (уберите все метки!)")
        self.calib_progress.setValue(0)
        
        # Запускаем таймер для прогресс-бара
        self.calib_start_time = time.time()
        self.calib_target_duration = duration
    
    def stop_calibration(self):
        """Остановить калибровку"""
        self.btn_start_calib.setEnabled(True)
        self.btn_stop_calib.setEnabled(False)
        self.calib_status.setText("✓ Калибровка завершена")
        self.calib_progress.setValue(100)
    
    def start_buffer_test(self):
        """Запустить тестирование буферов"""
        self.buffer_test_requested.emit()
        self.btn_buffer_test.setEnabled(False)
        self.buffer_status.setText("⏳ Тестирование... Подносите и убирайте метку!")
        
        # Через некоторое время включаем кнопку обратно
        QtCore.QTimer.singleShot(self.buffer_test_duration.value() * 1000, 
                                 lambda: self.btn_buffer_test.setEnabled(True))
    
    def send_feedback(self, feedback_type: str):
        """Отправить обратную связь"""
        self.feedback_signal.emit(feedback_type)
        
        # Визуальная обратная связь
        if feedback_type == 'marker':
            self.calib_status.setText("✓ Отмечено как правильное обнаружение")
        elif feedback_type == 'false_positive':
            self.calib_status.setText("✗ Отмечено как ложное срабатывание")
        elif feedback_type == 'missed':
            self.calib_status.setText("⊘ Отмечено как пропущенная метка")
    
    def update_stats_display(self):
        """Обновить отображение статистики"""
        try:
            stats = self.detector.get_comprehensive_stats()
            
            # Общая статистика
            det_stats = stats['detection']
            self.label_frames_total.setText(str(det_stats['total_frames']))
            self.label_noise_frames.setText(str(det_stats['noise_frames']))
            self.label_marker_frames.setText(str(det_stats['marker_frames']))
            self.label_false_positives.setText(str(det_stats['false_positives']))
            
            # Буферы
            buf_stats = stats['buffer_averaging']
            self.label_current_buffers.setText(str(buf_stats['current_buffers']))
            self.label_optimal_buffers.setText(str(buf_stats['optimal_buffers']))
            
            # Скорость
            self.label_detection_speed.setText(f"{det_stats['detection_speed_ms']:.2f} мс")
            
            # Пороги
            noise_stats = stats['noise_calibration']
            if noise_stats['ready']:
                self.label_threshold_ch0.setText(f"{noise_stats['ch0']['threshold']:.0f}")
                self.label_threshold_ch1.setText(f"{noise_stats['ch1']['threshold']:.0f}")
                self.label_noise_level.setText(
                    f"CH0: {noise_stats['ch0']['mean']:.0f} ± {noise_stats['ch0']['std']:.0f}, "
                    f"CH1: {noise_stats['ch1']['mean']:.0f} ± {noise_stats['ch1']['std']:.0f}"
                )
            
            # Прогресс калибровки
            if hasattr(self, 'calib_start_time') and self.btn_stop_calib.isEnabled():
                elapsed = time.time() - self.calib_start_time
                progress = min(100, int(elapsed / self.calib_target_duration * 100))
                self.calib_progress.setValue(progress)
                
                if progress >= 100:
                    self.stop_calibration()
            
            # Обновляем возраст данных
            if hasattr(self.detector, 'data_store'):
                age = self.detector.data_store.get_data_age()
                if age is not None:
                    hours = age.total_seconds() / 3600
                    if hours < 1:
                        age_str = f"{age.total_seconds() / 60:.0f} мин"
                    elif hours < 24:
                        age_str = f"{hours:.1f} ч"
                    else:
                        age_str = f"{hours / 24:.1f} дн"
                    self.label_data_age.setText(f"Данные: {age_str} назад")
                else:
                    self.label_data_age.setText("Данные: нет сохраненных данных")
            
        except Exception as e:
            print(f"[ADAPTIVE_GUI] Ошибка обновления статистики: {e}")
    
    def save_data_now(self):
        """Сохранить данные немедленно"""
        try:
            if self.detector.save_now():
                QtWidgets.QMessageBox.information(
                    self, "Успех",
                    "Данные успешно сохранены в ./adaptive_data/"
                )
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Ошибка",
                    "Не удалось сохранить данные"
                )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка",
                f"Ошибка сохранения: {e}"
            )
    
    def reset_all_data(self):
        """Сбросить все накопленные данные"""
        reply = QtWidgets.QMessageBox.question(
            self, "Подтверждение",
            "Вы уверены, что хотите удалить все накопленные данные?\n\n"
            "Это действие:\n"
            "• Удалит всю историю калибровки шума\n"
            "• Удалит адаптированные пороги\n"
            "• Создаст резервную копию перед удалением\n"
            "• Система начнет обучение заново\n\n"
            "Продолжить?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                if self.detector.reset_all_data():
                    QtWidgets.QMessageBox.information(
                        self, "Успех",
                        "Все данные сброшены.\n"
                        "Резервная копия сохранена в ./adaptive_data/backup/\n"
                        "Система начнет калибровку заново."
                    )
                else:
                    QtWidgets.QMessageBox.warning(
                        self, "Ошибка",
                        "Не удалось сбросить данные"
                    )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Ошибка",
                    f"Ошибка сброса данных: {e}"
                )
    
    def save_calibration(self):
        """Сохранить калибровку"""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить калибровку", 
            "./adaptive_calibration.json",
            "JSON Files (*.json)"
        )
        
        if filename:
            self.detector.save_calibration(filename)
            QtWidgets.QMessageBox.information(
                self, "Успех",
                f"Калибровка сохранена:\n{filename}"
            )
    
    def load_calibration(self):
        """Загрузить калибровку"""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Загрузить калибровку",
            "./",
            "JSON Files (*.json)"
        )
        
        if filename:
            if self.detector.load_calibration(filename):
                QtWidgets.QMessageBox.information(
                    self, "Успех",
                    f"Калибровка загружена:\n{filename}"
                )
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Ошибка",
                    "Не удалось загрузить калибровку"
                )


# Пример интеграции в основное окно
class AdaptiveDetectorWindow(QtWidgets.QMainWindow):
    """Отдельное окно для адаптивного детектора (для тестирования)"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Адаптивный детектор меток - Управление")
        self.setGeometry(100, 100, 500, 800)
        
        # Импортируем детектор
        from adaptive_realtime_detector import AdaptiveRealtimeDetector
        self.detector = AdaptiveRealtimeDetector()
        
        # Создаем панель
        self.panel = AdaptiveDetectorPanel(self.detector)
        self.setCentralWidget(self.panel)
        
        # Подключаем сигналы
        self.panel.calibration_requested.connect(self.on_calibration_requested)
        self.panel.buffer_test_requested.connect(self.on_buffer_test_requested)
        self.panel.feedback_signal.connect(self.on_feedback)
    
    def on_calibration_requested(self, duration: int):
        """Обработчик запроса калибровки"""
        print(f"[ADAPTIVE_WINDOW] Запуск калибровки на {duration} сек")
        self.detector.start_calibration_session(duration)
    
    def on_buffer_test_requested(self):
        """Обработчик запроса тестирования буферов"""
        print(f"[ADAPTIVE_WINDOW] Запуск тестирования буферов")
        self.detector.test_buffer_counts_auto()
    
    def on_feedback(self, feedback_type: str):
        """Обработчик обратной связи"""
        print(f"[ADAPTIVE_WINDOW] Обратная связь: {feedback_type}")
        # В реальной интеграции здесь будет вызов detector.process_frame с feedback


if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = AdaptiveDetectorWindow()
    window.show()
    sys.exit(app.exec_())
