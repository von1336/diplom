import os
from celery import Celery

# Устанавливаем модуль настроек Django по умолчанию для Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'netology_pd_diplom.settings')

app = Celery('netology_pd_diplom')

# Читаем конфигурацию из settings.py (все переменные с префиксом CELERY_)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически обнаруживаем задачи из всех установленных приложений
app.autodiscover_tasks()
