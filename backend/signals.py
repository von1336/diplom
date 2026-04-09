from typing import Type

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import Signal, receiver
from django_rest_passwordreset.signals import reset_password_token_created

from backend.models import ConfirmEmailToken, Product, User
from backend.tasks import dispatch_task, generate_thumbnails, send_email

new_user_registered = Signal()
new_order = Signal()


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, **kwargs):
    dispatch_task(
        send_email,
        subject=f'Password reset for {reset_password_token.user}',
        body=reset_password_token.key,
        to_emails=[reset_password_token.user.email],
    )


@receiver(post_save, sender=User)
def new_user_registered_signal(sender: Type[User], instance: User, created: bool, **kwargs):
    if created and not instance.is_active:
        token, _ = ConfirmEmailToken.objects.get_or_create(user_id=instance.pk)

        dispatch_task(
            send_email,
            subject=f'Registration confirmation for {instance.email}',
            body=f'Your confirmation token: {token.key}',
            to_emails=[instance.email],
        )


@receiver(new_order)
def new_order_signal(user_id, **kwargs):
    user = User.objects.get(id=user_id)

    dispatch_task(
        send_email,
        subject='Your order has been accepted',
        body=(
            f'Hello, {user.first_name}!\n\n'
            'Your order has been placed successfully and sent for processing.'
        ),
        to_emails=[user.email],
    )

    admin_email = getattr(settings, 'ADMIN_EMAIL', None)
    if admin_email:
        dispatch_task(
            send_email,
            subject=f'New order from {user.email}',
            body=(
                f'New order from {user.first_name} {user.last_name} '
                f'({user.email}) has been received.'
            ),
            to_emails=[admin_email],
        )


@receiver(post_save, sender=User)
def warm_user_avatar_thumbnails(sender: Type[User], instance: User, **kwargs):
    if instance.avatar:
        dispatch_task(
            generate_thumbnails,
            app_label='backend',
            model_name='User',
            object_id=instance.pk,
            image_field_name='avatar',
            aliases=['avatar_small', 'avatar_medium'],
        )


@receiver(post_save, sender=Product)
def warm_product_image_thumbnails(sender: Type[Product], instance: Product, **kwargs):
    if instance.image:
        dispatch_task(
            generate_thumbnails,
            app_label='backend',
            model_name='Product',
            object_id=instance.pk,
            image_field_name='image',
            aliases=['product_small', 'product_medium'],
        )
