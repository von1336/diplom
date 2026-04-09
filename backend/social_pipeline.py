def activate_social_user(backend, user=None, is_new=False, *args, **kwargs):
    """Активирует пользователя после входа через соцсеть и задаёт роль покупателя по умолчанию."""
    if user is None:
        return None

    fields_to_update = []
    if not user.is_active:
        user.is_active = True
        fields_to_update.append('is_active')

    if is_new and not user.type:
        user.type = 'buyer'
        fields_to_update.append('type')

    if not user.username and user.email:
        user.username = user.email
        fields_to_update.append('username')

    if fields_to_update:
        user.save(update_fields=fields_to_update)

    return {'user': user}
