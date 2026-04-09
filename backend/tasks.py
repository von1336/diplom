import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from kombu.exceptions import OperationalError
from yaml import safe_load


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
            'Брокер Celery недоступен для задачи %s, выполняю синхронно.',
            getattr(task, 'name', repr(task)),
        )
        return TaskDispatchResult(queued=False, result=task(*args, **kwargs))

    try:
        return TaskDispatchResult(queued=True, result=task.delay(*args, **kwargs))
    except OperationalError as error:
        logger.warning(
            'Брокер Celery недоступен для задачи %s, выполняю синхронно: %s',
            getattr(task, 'name', repr(task)),
            error,
        )
        return TaskDispatchResult(queued=False, result=task(*args, **kwargs))


@shared_task
def send_email(subject, body, to_emails):
    """Отправляет email-уведомление."""
    from_email = getattr(settings, 'EMAIL_HOST_USER', 'noreply@example.com')
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_email,
        to=to_emails,
    )
    message.send()
    return f'Email sent to: {", ".join(to_emails)}'


@shared_task
def do_import(url, user_id):
    """Импортирует товары поставщика из удалённого YAML-прайса."""
    from backend.models import Category, Parameter, Product, ProductInfo, ProductParameter, Shop

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = safe_load(response.content)

        shop, _ = Shop.objects.get_or_create(name=data['shop'], user_id=user_id)

        for category in data['categories']:
            category_object, _ = Category.objects.get_or_create(
                id=category['id'],
                name=category['name'],
            )
            category_object.shops.add(shop.id)
            category_object.save()

        ProductInfo.objects.filter(shop_id=shop.id).delete()

        for item in data['goods']:
            product, _ = Product.objects.get_or_create(
                name=item['name'],
                category_id=item['category'],
            )

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
    except Exception as error:
        logger.exception('Ошибка импорта для user_id=%s и url=%s', user_id, url)
        return f'Ошибка импорта: {error}'


@shared_task
def generate_thumbnails(app_label, model_name, object_id, image_field_name, aliases):
    """Генерирует миниатюры изображений в фоне."""
    try:
        from easy_thumbnails.files import get_thumbnailer
    except Exception:
        logger.warning('easy_thumbnails недоступен, генерация миниатюр пропущена.')
        return 'Генерация миниатюр пропущена'

    model = apps.get_model(app_label, model_name)
    if not model:
        return f'Модель не найдена: {app_label}.{model_name}'

    obj = model.objects.filter(pk=object_id).first()
    if not obj:
        return f'Объект не найден: {app_label}.{model_name}#{object_id}'

    image_field = getattr(obj, image_field_name, None)
    if not image_field:
        return f'Поле не найдено: {image_field_name}'
    if not getattr(image_field, 'name', None):
        return 'Изображение отсутствует'

    thumbnailer = get_thumbnailer(image_field)
    generated = 0
    aliases_map = settings.THUMBNAIL_ALIASES.get('', {})
    for alias in aliases:
        options = aliases_map.get(alias)
        if not options:
            continue
        thumbnailer.get_thumbnail(options)
        generated += 1

    return f'Сгенерировано миниатюр: {generated} для {app_label}.{model_name}#{object_id}'
