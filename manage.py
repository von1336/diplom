#!/usr/bin/env python
"""Командная утилита Django для административных задач."""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'netology_pd_diplom.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Не удалось импортировать Django. Проверьте, что он установлен "
            "и доступен в переменной окружения PYTHONPATH. Также убедитесь, "
            "что активировали виртуальное окружение."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
