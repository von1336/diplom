from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from django.conf import settings
from django.conf.urls.static import static
from backend.views import SentryDebugView, SocialAuthErrorRedirectView, SocialTokenBridgeView

urlpatterns = [
    path('', TemplateView.as_view(template_name='frontend/glass_index.html'), name='frontend-index'),
    path('baton/', include('baton.urls')),
    path('admin/', admin.site.urls),
    path('auth/token-bridge/', SocialTokenBridgeView.as_view(), name='social-token-bridge'),
    path('auth/error/', SocialAuthErrorRedirectView.as_view(), name='social-auth-error'),
    path('auth/', include('social_django.urls', namespace='social')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/v1/debug/sentry', SentryDebugView.as_view(), name='debug-sentry'),
    path('api/v1/', include('backend.urls', namespace='backend')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
