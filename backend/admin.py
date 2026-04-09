from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.shortcuts import redirect, render
from django.urls import path

from backend.models import (
    Category,
    ConfirmEmailToken,
    Contact,
    Order,
    OrderItem,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
    User,
)
from backend.tasks import dispatch_task, do_import

admin.site.site_header = 'VoN Administration'
admin.site.site_title = 'VoN Admin'
admin.site.index_title = 'VoN Control Panel'


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password', 'type')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'company', 'position', 'avatar', 'avatar_preview')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2', 'type', 'is_active', 'is_staff'),
            },
        ),
    )
    list_display = ('email', 'first_name', 'last_name', 'avatar_preview', 'is_staff', 'type', 'is_active')
    list_filter = ('type', 'is_active', 'is_staff')
    search_fields = ('email', 'first_name', 'last_name', 'company')
    readonly_fields = ('avatar_preview',)

    def avatar_preview(self, obj):
        if not obj.avatar:
            return 'Нет аватара'
        return format_html('<img src="{}" style="width:48px;height:48px;border-radius:50%;object-fit:cover;" />', obj.avatar.url)

    avatar_preview.short_description = 'Avatar'


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'state')
    list_filter = ('state',)
    search_fields = ('name', 'user__email')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import/', self.admin_site.admin_view(self.import_view), name='shop-import'),
        ]
        return custom_urls + urls

    def import_view(self, request):
        if request.method == 'POST':
            url = request.POST.get('url', '').strip()
            user_id = request.POST.get('user_id', '').strip()

            if url and user_id:
                execution = dispatch_task(do_import, url=url, user_id=int(user_id))
                if execution.queued:
                    self.message_user(
                        request,
                        f'Импорт запущен (task id: {execution.result.id}). Результат появится в логах Celery.',
                        messages.SUCCESS,
                    )
                elif isinstance(execution.result, str) and execution.result.startswith('Ошибка импорта:'):
                    self.message_user(request, execution.result, messages.ERROR)
                else:
                    self.message_user(request, execution.result, messages.SUCCESS)
                return redirect('..')

            self.message_user(request, 'Provide both URL and shop user ID.', messages.ERROR)

        shop_users = User.objects.filter(type='shop', is_active=True)
        context = {
            **self.admin_site.each_context(request),
            'title': 'Start goods import',
            'shop_users': shop_users,
        }
        return render(request, 'admin/glass_import.html', context)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    filter_horizontal = ('shops',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'image_preview')
    list_filter = ('category',)
    search_fields = ('name', 'category__name')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if not obj.image:
            return 'Нет изображения'
        return format_html('<img src="{}" style="width:72px;height:72px;border-radius:12px;object-fit:cover;" />', obj.image.url)

    image_preview.short_description = 'Image'


@admin.register(ProductInfo)
class ProductInfoAdmin(admin.ModelAdmin):
    list_display = ('product', 'shop', 'price', 'price_rrc', 'quantity')
    list_filter = ('shop',)
    search_fields = ('product__name', 'shop__name', 'model')


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    pass


@admin.register(ProductParameter)
class ProductParameterAdmin(admin.ModelAdmin):
    list_display = ('product_info', 'parameter', 'value')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'state', 'dt', 'contact')
    list_filter = ('state',)
    list_editable = ('state',)
    search_fields = ('user__email', 'contact__city', 'contact__street')


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_info', 'quantity')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'street', 'phone')
    search_fields = ('user__email', 'city', 'street', 'phone')


@admin.register(ConfirmEmailToken)
class ConfirmEmailTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'key', 'created_at')
