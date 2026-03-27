from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
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


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = (
        (None, {'fields': ('email', 'password', 'type')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'company', 'position')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    list_display = ('email', 'first_name', 'last_name', 'is_staff', 'type', 'is_active')
    list_filter = ('type', 'is_active', 'is_staff')


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'state')
    list_filter = ('state',)

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
                        f'Import started (task id: {execution.result.id}). Result will appear in Celery logs.',
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
        return render(request, 'admin/import.html', context)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    filter_horizontal = ('shops',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')
    list_filter = ('category',)


@admin.register(ProductInfo)
class ProductInfoAdmin(admin.ModelAdmin):
    list_display = ('product', 'shop', 'price', 'price_rrc', 'quantity')
    list_filter = ('shop',)


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


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_info', 'quantity')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'street', 'phone')


@admin.register(ConfirmEmailToken)
class ConfirmEmailTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'key', 'created_at')
