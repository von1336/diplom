import os

from celery import Celery


# Устанавливаем модуль настроек Django по умолчанию для Celery.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'netology_pd_diplom.settings')

app = Celery('netology_pd_diplom')

# Загружаем конфигурацию из settings.py по префиксу CELERY_.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически находим задачи во всех установленных приложениях.
app.autodiscover_tasks()
