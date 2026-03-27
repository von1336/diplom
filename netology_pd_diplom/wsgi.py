import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'netology_pd_diplom.settings')

application = get_wsgi_application()
