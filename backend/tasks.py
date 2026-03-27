import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from kombu.exceptions import OperationalError


logger = logging.getLogger(__name__)


@dataclass
class TaskDispatchResult:
    queued: bool
    result: Any


def broker_is_available(task) -> bool:
    broker_url = getattr(task.app.conf, 'broker_url', None) or getattr(settings, 'CELERY_BROKER_URL', '')
    if not isinstance(broker_url, str):
        return True

    parsed = urlparse(broker_url)

    if not parsed.hostname or not parsed.port:
        return True

    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=0.5):
            return True
    except OSError:
        return False


def dispatch_task(task, *args, **kwargs):
    if not broker_is_available(task):
        logger.warning(
            'Celery broker is unavailable for task %s, running synchronously.',
            getattr(task, 'name', repr(task)),
        )
        return TaskDispatchResult(queued=False, result=task(*args, **kwargs))

    try:
        return TaskDispatchResult(queued=True, result=task.delay(*args, **kwargs))
    except OperationalError as error:
        logger.warning(
            'Celery broker is unavailable for task %s, running synchronously: %s',
            getattr(task, 'name', repr(task)),
            error,
        )
        return TaskDispatchResult(queued=False, result=task(*args, **kwargs))


@shared_task
def send_email(subject, body, to_emails):
    """
    Асинхронная задача отправки email.
    Принимает тему, тело письма и список адресатов.
    """
    from_email = getattr(settings, 'EMAIL_HOST_USER', 'noreply@example.com')
    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to_emails,
    )
    msg.send()
    return f'Email отправлен на: {", ".join(to_emails)}'


@shared_task
def do_import(url, user_id):
    """
    Асинхронная задача импорта товаров из YAML-файла по URL.
    Используется партнёрами для обновления прайса в фоновом режиме.
    """
    from requests import get
    from yaml import load as load_yaml, Loader
    from backend.models import Shop, Category, Product, ProductInfo, Parameter, ProductParameter

    try:
        stream = get(url).content
        data = load_yaml(stream, Loader=Loader)

        # Создаём или находим магазин текущего пользователя
        shop, _ = Shop.objects.get_or_create(name=data['shop'], user_id=user_id)

        # Обновляем категории и привязываем к магазину
        for category in data['categories']:
            category_object, _ = Category.objects.get_or_create(id=category['id'], name=category['name'])
            category_object.shops.add(shop.id)
            category_object.save()

        # Удаляем старые записи ProductInfo магазина (полная замена)
        ProductInfo.objects.filter(shop_id=shop.id).delete()

        # Создаём новые товары и их параметры
        for item in data['goods']:
            product, _ = Product.objects.get_or_create(name=item['name'], category_id=item['category'])

            product_info = ProductInfo.objects.create(
                product_id=product.id,
                external_id=item['id'],
                model=item['model'],
                price=item['price'],
                price_rrc=item['price_rrc'],
                quantity=item['quantity'],
                shop_id=shop.id,
            )

            for name, value in item['parameters'].items():
                parameter_object, _ = Parameter.objects.get_or_create(name=name)
                ProductParameter.objects.create(
                    product_info_id=product_info.id,
                    parameter_id=parameter_object.id,
                    value=str(value),
                )

        return f'Импорт завершён: магазин "{data["shop"]}", товаров {len(data["goods"])}'

    except Exception as e:
        # Возвращаем описание ошибки для логирования в Celery
        return f'Ошибка импорта: {str(e)}'
