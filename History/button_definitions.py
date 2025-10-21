import numpy as np

# Централизованное хранилище конфигураций кнопок
BUTTON_CONFIG = {
    0: {
        'description': 'Выключаем осциллограмму, но программа работает',
        'show_plot': False,
        'ylim': None,
    },
    1: {
        'description': 'Верхняя и нижняя антенны (сырые данные)',
        'show_plot': True,
        'ylim': (-35000, 44000),
        'setup': lambda params: {
            'x_axis': np.arange(params['start_sample'], params['start_sample'] + params['num_samples']),
            'line1_data': (lambda x: (x, params['dataADC_P1'][params['start_sample']:params['start_sample'] + params['num_samples']]))(np.arange(params['start_sample'], params['start_sample'] + params['num_samples'])),
            'line2_data': (lambda x: (x, params['dataADC_L1'][params['start_sample']:params['start_sample'] + params['num_samples']]))(np.arange(params['start_sample'], params['start_sample'] + params['num_samples'])),
            'line1_label': 'Верхняя Антенна',
            'line2_label': 'Нижняя Антенна',
            'line1_color': 'purple',
            'line2_color': 'chocolate',
            'line1_visible': True,
            'line2_visible': True,
            'xlim': (params['start_sample'], params['start_sample'] + params['num_samples'])
        }
    },
    # Добавьте определения для кнопок 2-15
    12: {
        'description': '12 периодов верхней антенны',
        'show_plot': True,
        'ylim': (-5000, 5000),
        'setup': lambda params: {
            'custom_plot': True,  # Флаг для особой обработки
            'xlim': (0, 200)
        }
    }
}

def get_button_config(button_id):
    """Возвращает конфигурацию для указанной кнопки"""
    return BUTTON_CONFIG.get(button_id, {
        'description': f'Резерв {button_id}',
        'show_plot': True,
        'ylim': None
    })