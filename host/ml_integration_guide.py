"""
Интеграция ML-детектора меток в BMI30.200.py
Патч для добавления ML-функционала в существующее приложение
"""

# Этот код нужно добавить в BMI30.200.py

# 1. В начало файла, после импортов:
"""
# ML marker detection (optional)
try:
    from ml_marker_detector import MLMarkerDetector
    ML_AVAILABLE = True
except Exception as e:
    print(f"[ML] ML marker detector not available: {e}")
    ML_AVAILABLE = False
"""

# 2. В __init__ метод SignalWindow, после инициализации auto_capture:
"""
        # --- ML Marker Detection (optional) ---
        self._ml_enabled = ML_AVAILABLE and _env_bool('BMI30_ML_ENABLE', False)
        if self._ml_enabled:
            try:
                ml_model_path = str(os.getenv('BMI30_ML_MODEL_PATH', './ml_model.json'))
                self._ml_detector = MLMarkerDetector(
                    model_path=ml_model_path,
                    training_data_dir=self._capture_dir
                )
                print(f"[ML] ML detector enabled, model: {ml_model_path}")
            except Exception as e:
                print(f"[ML] Failed to initialize ML detector: {e}")
                self._ml_enabled = False
                self._ml_detector = None
        else:
            self._ml_detector = None
        
        # ML prediction cache
        self._ml_last_prediction = 0
        self._ml_last_confidence = 0.0
        self._ml_prediction_count = 0
"""

# 3. В метод _detect_signal (после вычисления det_lvl0, det_lvl1):
"""
        # === ML-based detection (if enabled) ===
        ml_fire0 = False
        ml_fire1 = False
        ml_confidence = 0.0
        
        if self._ml_enabled and self._ml_detector is not None:
            try:
                # Используем последние фреймы из буфера для ML-предсказания
                with self._capture_buffer_lock:
                    recent_frames = list(self._capture_buffer[-5:])  # последние 5 фреймов
                
                if len(recent_frames) >= 3:  # минимум 3 фрейма для анализа
                    is_marker, marker_type, confidence = self._ml_detector.is_marker_detected(
                        recent_frames, 
                        confidence_threshold=0.6
                    )
                    
                    ml_confidence = confidence
                    self._ml_last_prediction = marker_type
                    self._ml_last_confidence = confidence
                    self._ml_prediction_count += 1
                    
                    if is_marker:
                        # ML предсказывает наличие метки
                        # Можно использовать это как дополнительный фактор
                        # или заменить пороговую логику полностью
                        
                        # Вариант 1: ML как дополнительный фактор (AND с пороговой логикой)
                        # fire0 = fire0 and (marker_type > 0)
                        
                        # Вариант 2: ML как основной детектор (заменяет пороговую логику)
                        if marker_type == 1:  # Метка на канале 0
                            ml_fire0 = True
                        elif marker_type == 2:  # Метка на канале 1
                            ml_fire1 = True
                        else:  # Общая метка
                            ml_fire0 = True
                            ml_fire1 = True
            
            except Exception as e:
                if self.debug_markers:
                    print(f"[ML] Prediction error: {e}")
        
        # Комбинируем результаты классической и ML-детекции
        if self._ml_enabled and ml_confidence > 0.7:
            # Высокая уверенность ML - используем ML-результат
            fire0 = ml_fire0
            fire1 = ml_fire1
        # else: используем классическую пороговую логику (fire0, fire1 уже вычислены)
"""

# 4. В метод _save_capture_session (после сохранения metadata):
"""
        # Обновляем ML-модель с новыми данными (если включено онлайн-обучение)
        if self._ml_enabled and self._ml_detector is not None:
            try:
                online_learning = _env_bool('BMI30_ML_ONLINE_LEARNING', False)
                if online_learning and session_metadata.get('label', 0) > 0:
                    # Есть метка от пользователя - используем для онлайн-обучения
                    true_label = session_metadata['label']
                    confidence = session_metadata.get('label_confidence', 1.0)
                    
                    self._ml_detector.update_with_feedback(
                        session['frames'], 
                        true_label, 
                        confidence
                    )
                    print(f"[ML] Online learning update: label={true_label}, confidence={confidence}")
            except Exception as e:
                print(f"[ML] Online learning error: {e}")
"""

# 5. Добавить в status bar обновление (в методе update_ui):
"""
        # ML status (if enabled)
        if self._ml_enabled and self._ml_detector is not None:
            ml_stats = self._ml_detector.get_statistics()
            ml_status = f"ML: {ml_stats['total_predictions']} pred, {ml_stats['accuracy']:.1f}% acc"
            status_parts.append(ml_status)
            
            if self._ml_last_confidence > 0:
                class_names = {0: "шум", 1: "метка_A", 2: "метка_B"}
                ml_status += f" | Последнее: {class_names.get(self._ml_last_prediction, '?')} ({self._ml_last_confidence:.1f})"
"""

# 6. Добавить кнопку в GUI для ML-тренировки:
"""
        # ML training button
        if ML_AVAILABLE:
            self.btn_ml_train = QtWidgets.QPushButton("🎓 ML")
            self.btn_ml_train.setCheckable(False)
            self.btn_ml_train.setToolTip("Открыть окно обучения ML-модели")
            self.btn_ml_train.clicked.connect(self._open_ml_training)
            top_panel.addWidget(self.btn_ml_train)
"""

# 7. Добавить метод для открытия окна тренировки:
"""
    def _open_ml_training(self):
        '''Открыть окно обучения ML-модели'''
        try:
            from ml_training_gui import MLTrainingWindow
            
            if not hasattr(self, '_ml_training_window') or self._ml_training_window is None:
                self._ml_training_window = MLTrainingWindow()
            
            self._ml_training_window.show()
            self._ml_training_window.raise_()
            self._ml_training_window.activateWindow()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка",
                f"Не удалось открыть окно ML-тренировки:\n{e}"
            )
"""

print("""
ИНСТРУКЦИЯ ПО ИНТЕГРАЦИИ ML-СИСТЕМЫ:

1. Установите необходимые зависимости:
   pip install scikit-learn  # опционально для более продвинутых моделей

2. Скопируйте файлы:
   - ml_marker_detector.py
   - ml_training_gui.py
   в папку host/

3. Добавьте код из этого файла в BMI30.200.py в указанные места

4. Установите переменные окружения для включения ML:
   export BMI30_ML_ENABLE=1
   export BMI30_ML_MODEL_PATH=./ml_model.json
   export BMI30_ML_ONLINE_LEARNING=1  # для онлайн-обучения

5. ПРОЦЕСС РАБОТЫ:
   
   a) Первичный сбор данных:
      - Запустите BMI30.200.py с включенным автозахватом (кнопка "Автозахват")
      - Соберите ~50-100 примеров различных сигналов
      - Захваты сохранятся в ./captures/
   
   b) Разметка данных:
      - Запустите: python ml_training_gui.py
      - Просмотрите каждый захват
      - Назначьте метки: "Метка" или "Шум"
      - Сохраните метки
   
   c) Обучение модели:
      - В окне ML-тренировки нажмите "Обучить модель"
      - Модель сохранится в ml_model.json
   
   d) Использование в реальном времени:
      - Запустите BMI30.200.py с BMI30_ML_ENABLE=1
      - ML-система будет использоваться для детекции
      - При онлайн-обучении модель будет улучшаться автоматически

6. НАСТРОЙКИ (переменные окружения):
   
   BMI30_ML_ENABLE=1                    # включить ML-детекцию
   BMI30_ML_MODEL_PATH=./ml_model.json  # путь к модели
   BMI30_ML_ONLINE_LEARNING=1           # онлайн-обучение
   BMI30_ML_CONFIDENCE_THRESHOLD=0.6    # порог уверенности

7. ПРЕИМУЩЕСТВА ML-СИСТЕМЫ:
   
   ✓ Автоматическая адаптация к различным типам меток
   ✓ Уменьшение ложных срабатываний от шумов
   ✓ Обучение на реальных данных от вашего устройства
   ✓ Онлайн-обучение - модель улучшается со временем
   ✓ Извлечение множества признаков (временная, частотная область)
   ✓ Простой GUI для разметки и тренировки

8. РАСШИРЕННАЯ РАЗМЕТКА:
   
   Можно добавить больше типов меток:
   - Метка типа A (например, медленная)
   - Метка типа B (например, быстрая)
   - Метка типа C (например, двойная)
   - Шум
   - Артефакты
   
   Для этого измените словарь class_names в обоих скриптах.

Готово! Система самообучения готова к использованию.
""")
