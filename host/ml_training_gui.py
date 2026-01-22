"""
GUI для обучения и тестирования ML-системы определения меток
Позволяет просматривать захваченные данные, размечать их и обучать модель
"""

import sys
import os
import numpy as np
from pathlib import Path
from datetime import datetime

# Qt setup
if "QT_QPA_PLATFORM" not in os.environ:
    if os.getenv("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    elif os.getenv("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg  # type: ignore

from ml_marker_detector import MLMarkerDetector, FeatureExtractor


class CaptureViewer(QtWidgets.QWidget):
    """Виджет для просмотра захваченных данных"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_file = None
        self.current_data = None
        self.current_label = 0  # 0=неизвестно, 1=метка, 2=шум
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Информация о файле
        info_layout = QtWidgets.QHBoxLayout()
        self.file_label = QtWidgets.QLabel("Файл не выбран")
        self.file_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.file_label)
        info_layout.addStretch()
        
        self.frame_count_label = QtWidgets.QLabel("Фреймов: 0")
        info_layout.addWidget(self.frame_count_label)
        
        layout.addLayout(info_layout)
        
        # Графики
        self.plot_widget = pg.GraphicsLayoutWidget()
        
        # График ADC0
        self.plot_adc0 = self.plot_widget.addPlot(row=0, col=0, title="ADC0")
        self.plot_adc0.showGrid(x=True, y=True, alpha=0.3)
        self.plot_adc0.setLabel('left', 'Амплитуда')
        self.plot_adc0.setLabel('bottom', 'Отсчеты')
        
        # График ADC1
        self.plot_adc1 = self.plot_widget.addPlot(row=1, col=0, title="ADC1")
        self.plot_adc1.showGrid(x=True, y=True, alpha=0.3)
        self.plot_adc1.setLabel('left', 'Амплитуда')
        self.plot_adc1.setLabel('bottom', 'Отсчеты')
        
        # График корреляции
        self.plot_corr = self.plot_widget.addPlot(row=2, col=0, title="Корреляция")
        self.plot_corr.showGrid(x=True, y=True, alpha=0.3)
        self.plot_corr.setLabel('left', 'Корреляция')
        self.plot_corr.setLabel('bottom', 'Отсчеты')
        
        layout.addWidget(self.plot_widget)
        
        # Кнопки управления
        button_layout = QtWidgets.QHBoxLayout()
        
        self.btn_prev = QtWidgets.QPushButton("◀ Предыдущий")
        self.btn_prev.clicked.connect(lambda: self.parent().load_prev_capture())
        button_layout.addWidget(self.btn_prev)
        
        self.btn_next = QtWidgets.QPushButton("Следующий ▶")
        self.btn_next.clicked.connect(lambda: self.parent().load_next_capture())
        button_layout.addWidget(self.btn_next)
        
        button_layout.addStretch()
        
        # Кнопки разметки
        label_group = QtWidgets.QGroupBox("Метка:")
        label_layout = QtWidgets.QHBoxLayout()
        
        self.btn_label_unknown = QtWidgets.QPushButton("❓ Неизвестно")
        self.btn_label_unknown.setCheckable(True)
        self.btn_label_unknown.clicked.connect(lambda: self.set_label(0))
        label_layout.addWidget(self.btn_label_unknown)
        
        self.btn_label_marker = QtWidgets.QPushButton("✓ Метка")
        self.btn_label_marker.setCheckable(True)
        self.btn_label_marker.clicked.connect(lambda: self.set_label(1))
        label_layout.addWidget(self.btn_label_marker)
        
        self.btn_label_noise = QtWidgets.QPushButton("✗ Шум")
        self.btn_label_noise.setCheckable(True)
        self.btn_label_noise.clicked.connect(lambda: self.set_label(2))
        label_layout.addWidget(self.btn_label_noise)
        
        label_group.setLayout(label_layout)
        button_layout.addWidget(label_group)
        
        self.btn_save = QtWidgets.QPushButton("💾 Сохранить метку")
        self.btn_save.clicked.connect(self.save_label)
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        button_layout.addWidget(self.btn_save)
        
        layout.addLayout(button_layout)
        
        # Статистика признаков
        self.features_text = QtWidgets.QTextEdit()
        self.features_text.setReadOnly(True)
        self.features_text.setMaximumHeight(150)
        layout.addWidget(QtWidgets.QLabel("Извлеченные признаки:"))
        layout.addWidget(self.features_text)
        
        self.update_label_buttons()
    
    def set_label(self, label: int):
        """Установить метку для текущего файла"""
        self.current_label = label
        self.update_label_buttons()
    
    def update_label_buttons(self):
        """Обновить состояние кнопок меток"""
        self.btn_label_unknown.setChecked(self.current_label == 0)
        self.btn_label_marker.setChecked(self.current_label == 1)
        self.btn_label_noise.setChecked(self.current_label == 2)
    
    def load_file(self, filepath: str):
        """Загрузить NPZ файл"""
        try:
            self.current_file = filepath
            data = np.load(filepath, allow_pickle=True)
            
            # Извлекаем метаданные
            metadata = data.get('metadata', None)
            if metadata is not None:
                metadata = metadata.item()
                self.current_label = metadata.get('label', 0)
            else:
                self.current_label = 0
            
            # Извлекаем фреймы
            frames = []
            frame_keys = sorted([k for k in data.keys() if k.startswith('frame_')])
            for frame_key in frame_keys:
                frame_data = data[frame_key].item()
                frames.append(frame_data)
            
            self.current_data = frames
            
            # Обновляем UI
            self.file_label.setText(f"Файл: {Path(filepath).name}")
            self.frame_count_label.setText(f"Фреймов: {len(frames)}")
            self.update_label_buttons()
            
            # Отображаем данные
            self.plot_data(frames)
            
            # Извлекаем и показываем признаки
            self.show_features(frames)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл:\n{e}")
    
    def plot_data(self, frames: list):
        """Отобразить данные на графиках"""
        if not frames:
            return
        
        # Объединяем все фреймы
        all_adc0 = np.concatenate([f['adc0'] for f in frames])
        all_adc1 = np.concatenate([f['adc1'] for f in frames])
        all_corr = np.concatenate([f['correlation'] for f in frames])
        
        # Очищаем графики
        self.plot_adc0.clear()
        self.plot_adc1.clear()
        self.plot_corr.clear()
        
        # Отображаем
        self.plot_adc0.plot(all_adc0, pen='r')
        self.plot_adc1.plot(all_adc1, pen='b')
        self.plot_corr.plot(all_corr, pen='g')
    
    def show_features(self, frames: list):
        """Показать извлеченные признаки"""
        if not frames:
            return
        
        try:
            extractor = FeatureExtractor()
            features = extractor.extract_from_sequence(frames)
            
            # Форматируем текст
            text = "{\n"
            for key, value in sorted(features.items()):
                text += f"  {key}: {value:.4f}\n"
            text += "}"
            
            self.features_text.setPlainText(text)
        except Exception as e:
            self.features_text.setPlainText(f"Ошибка извлечения признаков: {e}")
    
    def save_label(self):
        """Сохранить метку обратно в файл"""
        if self.current_file is None or self.current_data is None:
            return
        
        try:
            # Загружаем существующие данные
            data = np.load(self.current_file, allow_pickle=True)
            
            # Обновляем метаданные
            metadata = data.get('metadata', None)
            if metadata is not None:
                metadata = metadata.item()
            else:
                metadata = {}
            
            metadata['label'] = self.current_label
            metadata['label_timestamp'] = datetime.now().isoformat()
            metadata['label_confidence'] = 1.0  # Пользователь уверен
            
            # Пересохраняем файл
            save_dict = {'metadata': metadata}
            for key in data.keys():
                if key.startswith('frame_'):
                    save_dict[key] = data[key]
            
            np.savez(self.current_file, **save_dict)
            
            QtWidgets.QMessageBox.information(self, "Успех", "Метка сохранена!")
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить метку:\n{e}")


class MLTrainingWindow(QtWidgets.QMainWindow):
    """Главное окно приложения для обучения ML-модели"""
    
    def __init__(self):
        super().__init__()
        self.capture_dir = './captures'
        self.capture_files = []
        self.current_index = 0
        self.detector = MLMarkerDetector(model_path='./ml_model.json', 
                                        training_data_dir=self.capture_dir)
        
        self.init_ui()
        self.load_capture_list()
    
    def init_ui(self):
        self.setWindowTitle("ML Обучение - Система определения меток BMI30")
        self.setGeometry(100, 100, 1200, 800)
        
        # Центральный виджет
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        
        # Верхняя панель с кнопками управления
        control_panel = QtWidgets.QHBoxLayout()
        
        self.btn_load_dir = QtWidgets.QPushButton("📁 Выбрать папку с данными")
        self.btn_load_dir.clicked.connect(self.select_directory)
        control_panel.addWidget(self.btn_load_dir)
        
        self.btn_train = QtWidgets.QPushButton("🎓 Обучить модель")
        self.btn_train.clicked.connect(self.train_model)
        self.btn_train.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        control_panel.addWidget(self.btn_train)
        
        self.btn_test = QtWidgets.QPushButton("🧪 Тестировать")
        self.btn_test.clicked.connect(self.test_model)
        control_panel.addWidget(self.btn_test)
        
        self.btn_stats = QtWidgets.QPushButton("📊 Статистика")
        self.btn_stats.clicked.connect(self.show_statistics)
        control_panel.addWidget(self.btn_stats)
        
        control_panel.addStretch()
        
        self.file_counter_label = QtWidgets.QLabel("Файлов: 0")
        control_panel.addWidget(self.file_counter_label)
        
        main_layout.addLayout(control_panel)
        
        # Viewer
        self.viewer = CaptureViewer(self)
        main_layout.addWidget(self.viewer)
        
        # Статус бар
        self.statusBar().showMessage("Готов к работе")
    
    def select_directory(self):
        """Выбрать директорию с захваченными данными"""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Выберите папку с данными", self.capture_dir
        )
        if directory:
            self.capture_dir = directory
            self.detector.training_data_dir = directory
            self.load_capture_list()
    
    def load_capture_list(self):
        """Загрузить список файлов захватов"""
        self.capture_files = sorted(Path(self.capture_dir).glob('*.npz'))
        self.file_counter_label.setText(f"Файлов: {len(self.capture_files)}")
        
        if self.capture_files:
            self.current_index = 0
            self.viewer.load_file(str(self.capture_files[self.current_index]))
        else:
            self.statusBar().showMessage(f"Нет файлов в {self.capture_dir}")
    
    def load_next_capture(self):
        """Загрузить следующий захват"""
        if not self.capture_files:
            return
        
        self.current_index = (self.current_index + 1) % len(self.capture_files)
        self.viewer.load_file(str(self.capture_files[self.current_index]))
        self.statusBar().showMessage(f"Файл {self.current_index + 1} из {len(self.capture_files)}")
    
    def load_prev_capture(self):
        """Загрузить предыдущий захват"""
        if not self.capture_files:
            return
        
        self.current_index = (self.current_index - 1) % len(self.capture_files)
        self.viewer.load_file(str(self.capture_files[self.current_index]))
        self.statusBar().showMessage(f"Файл {self.current_index + 1} из {len(self.capture_files)}")
    
    def train_model(self):
        """Обучить ML-модель на размеченных данных"""
        reply = QtWidgets.QMessageBox.question(
            self, "Обучение модели",
            f"Обучить модель на всех размеченных данных из {self.capture_dir}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.statusBar().showMessage("Обучение модели...")
            QtWidgets.QApplication.processEvents()
            
            try:
                self.detector.train_from_directory(self.capture_dir)
                self.statusBar().showMessage("Модель обучена успешно!")
                QtWidgets.QMessageBox.information(
                    self, "Успех",
                    "Модель обучена и сохранена в ml_model.json"
                )
            except Exception as e:
                self.statusBar().showMessage("Ошибка обучения")
                QtWidgets.QMessageBox.critical(
                    self, "Ошибка",
                    f"Не удалось обучить модель:\n{e}"
                )
    
    def test_model(self):
        """Протестировать модель на текущем файле"""
        if self.viewer.current_data is None:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Сначала загрузите файл")
            return
        
        try:
            predicted_class, confidence, features = self.detector.predict_from_frames(
                self.viewer.current_data
            )
            
            class_names = {0: "Неизвестно/Шум", 1: "Метка типа A", 2: "Метка типа B"}
            true_label = self.viewer.current_label
            
            result_text = f"Истинная метка: {class_names.get(true_label, 'N/A')}\n"
            result_text += f"Предсказано: {class_names.get(predicted_class, 'N/A')}\n"
            result_text += f"Уверенность: {confidence:.2%}\n\n"
            
            if predicted_class == true_label:
                result_text += "✓ ПРАВИЛЬНО"
            else:
                result_text += "✗ ОШИБКА"
            
            QtWidgets.QMessageBox.information(self, "Результат теста", result_text)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Ошибка тестирования:\n{e}")
    
    def show_statistics(self):
        """Показать статистику модели"""
        try:
            stats = self.detector.get_statistics()
            
            text = "Статистика ML-модели:\n\n"
            text += f"Всего предсказаний: {stats['total_predictions']}\n"
            text += f"Правильных: {stats['correct_predictions']}\n"
            text += f"Точность: {stats['accuracy']:.1f}%\n\n"
            text += f"Ложные срабатывания: {stats['false_positives']}\n"
            text += f"Пропуски меток: {stats['false_negatives']}\n\n"
            text += "Образцов по классам:\n"
            for class_id, count in stats['samples_per_class'].items():
                class_names = {0: "Шум", 1: "Метка A", 2: "Метка B"}
                text += f"  {class_names.get(class_id, f'Класс {class_id}')}: {count}\n"
            
            QtWidgets.QMessageBox.information(self, "Статистика", text)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Ошибка получения статистики:\n{e}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MLTrainingWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
