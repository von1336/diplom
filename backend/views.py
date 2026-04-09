from json import loads as load_json

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.db.models import F, Q, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.views import View
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.models import (
    Category,
    ConfirmEmailToken,
    Contact,
    Order,
    OrderItem,
    ProductInfo,
    Shop,
)
from backend.serializers import (
    AccountUpdateSerializer,
    BasketItemsSerializer,
    CategorySerializer,
    ConfirmAccountSerializer,
    ContactSerializer,
    ContactDeleteSerializer,
    LoginSerializer,
    MessageResponseSerializer,
    OrderCreateSerializer,
    OrderItemSerializer,
    OrderSerializer,
    PartnerImportSerializer,
    PartnerStateUpdateSerializer,
    ProductInfoSerializer,
    RegisterSerializer,
    ShopSerializer,
    StatusResponseSerializer,
    TokenResponseSerializer,
    UserSerializer,
)
from backend.signals import new_order
from backend.tasks import dispatch_task, do_import


def strtobool(val):
    if isinstance(val, bool):
        return val
    val = str(val).lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    if val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    raise ValueError(f'invalid truth value {val!r}')


def partner_shop_missing_response():
    return JsonResponse(
        {'Status': False, 'Errors': 'Shop is missing. Upload a price list first.'},
        status=404,
    )


class RegisterAccount(APIView):
    """Создаёт новую учётную запись покупателя или поставщика."""

    throttle_scope = 'register'

    @extend_schema(
        tags=['Authentication'],
        summary='Register a new account',
        description='Creates a user account and stores the password securely.',
        request=RegisterSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        required_fields = {'first_name', 'last_name', 'email', 'password', 'company', 'position'}
        if not required_fields.issubset(request.data):
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        try:
            validate_password(request.data['password'])
        except Exception as password_error:
            return JsonResponse({'Status': False, 'Errors': {'password': list(password_error)}})

        user_serializer = UserSerializer(data=request.data)
        if not user_serializer.is_valid():
            return JsonResponse({'Status': False, 'Errors': user_serializer.errors})

        user = user_serializer.save()
        user.set_password(request.data['password'])
        user.save()
        return JsonResponse({'Status': True})


class ConfirmAccount(APIView):
    """Подтверждает учётную запись пользователя по email-токену."""

    throttle_scope = 'confirm'

    @extend_schema(
        tags=['Authentication'],
        summary='Confirm email token',
        description='Activates an account after the user submits the confirmation token.',
        request=ConfirmAccountSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not {'email', 'token'}.issubset(request.data):
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        token = ConfirmEmailToken.objects.filter(
            user__email=request.data['email'],
            key=request.data['token'],
        ).first()
        if not token:
            return JsonResponse({'Status': False, 'Errors': 'Invalid token or email'})

        token.user.is_active = True
        token.user.save()
        token.delete()
        return JsonResponse({'Status': True})


class AccountDetails(APIView):
    """Читает и обновляет профиль авторизованного пользователя."""

    @extend_schema(tags=['Account'], summary='Get current user profile', responses={200: UserSerializer})
    def get(self, request: Request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        tags=['Account'],
        summary='Update current user profile',
        request=AccountUpdateSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if 'password' in request.data:
            try:
                validate_password(request.data['password'])
            except Exception as password_error:
                return JsonResponse({'Status': False, 'Errors': {'password': list(password_error)}})
            request.user.set_password(request.data['password'])

        user_serializer = UserSerializer(request.user, data=request.data, partial=True)
        if not user_serializer.is_valid():
            return JsonResponse({'Status': False, 'Errors': user_serializer.errors})

        user_serializer.save()
        return JsonResponse({'Status': True})


class LoginAccount(APIView):
    """Аутентифицирует пользователя и выдаёт API-токен."""

    throttle_scope = 'login'

    @extend_schema(
        tags=['Authentication'],
        summary='Log in with email and password',
        description='Returns an auth token for subsequent API requests.',
        request=LoginSerializer,
        responses={200: TokenResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not {'email', 'password'}.issubset(request.data):
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        user = authenticate(request, username=request.data['email'], password=request.data['password'])
        if user is not None and user.is_active:
            token, _ = Token.objects.get_or_create(user=user)
            return JsonResponse({'Status': True, 'Token': token.key})

        return JsonResponse({'Status': False, 'Errors': 'Authentication failed'})


class CategoryView(ListAPIView):
    """Возвращает доступные категории товаров."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ShopView(ListAPIView):
    """Возвращает активные магазины поставщиков."""

    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer


class ProductInfoView(APIView):
    """Возвращает товары поставщиков с фильтрацией по магазину и категории."""

    @extend_schema(
        tags=['Catalog'],
        summary='List product offers',
        parameters=[
            OpenApiParameter(name='shop_id', description='Filter by shop id', required=False, type=int),
            OpenApiParameter(name='category_id', description='Filter by category id', required=False, type=int),
        ],
        responses={200: ProductInfoSerializer(many=True)},
    )
    def get(self, request: Request, *args, **kwargs):
        query = Q(shop__state=True)
        shop_id = request.query_params.get('shop_id')
        category_id = request.query_params.get('category_id')
        cache_key = f'products:shop={shop_id or "all"}:category={category_id or "all"}'

        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return Response(cached_payload)

        if shop_id:
            query &= Q(shop_id=shop_id)

        if category_id:
            query &= Q(product__category_id=category_id)

        queryset = (
            ProductInfo.objects.filter(query)
            .select_related('shop', 'product__category')
            .prefetch_related('product_parameters__parameter')
            .distinct()
        )

        serializer = ProductInfoSerializer(queryset, many=True, context={'request': request})
        payload = serializer.data
        cache.set(cache_key, payload, timeout=60)
        return Response(payload)


class BasketView(APIView):
    """Управляет позициями корзины авторизованного покупателя."""

    @extend_schema(tags=['Basket'], summary='Get current basket', responses={200: OrderSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        basket = (
            Order.objects.filter(user_id=request.user.id, state='basket')
            .prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter',
            )
            .annotate(total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price')))
            .distinct()
        )

        serializer = OrderSerializer(basket, many=True, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        tags=['Basket'],
        summary='Add items to basket',
        request=BasketItemsSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        items_string = request.data.get('items')
        if not items_string:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        try:
            items_dict = items_string if isinstance(items_string, list) else load_json(items_string)
        except ValueError:
            return JsonResponse({'Status': False, 'Errors': 'Invalid request format'})

        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
        objects_created = 0
        for order_item in items_dict:
            order_item.update({'order': basket.id})
            serializer = OrderItemSerializer(data=order_item)
            if not serializer.is_valid():
                return JsonResponse({'Status': False, 'Errors': serializer.errors})

            try:
                serializer.save()
            except IntegrityError as error:
                return JsonResponse({'Status': False, 'Errors': str(error)})
            objects_created += 1

        return JsonResponse({'Status': True, 'Created objects': objects_created})

    @extend_schema(
        tags=['Basket'],
        summary='Delete items from basket',
        request=ContactDeleteSerializer,
        responses={200: StatusResponseSerializer},
    )
    def delete(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        items_string = request.data.get('items')
        if not items_string:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        items_list = [str(item) for item in items_string] if isinstance(items_string, list) else items_string.split(',')
        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
        query = Q()
        objects_deleted = False
        for order_item_id in items_list:
            if str(order_item_id).isdigit():
                query |= Q(order_id=basket.id, id=order_item_id)
                objects_deleted = True

        if not objects_deleted:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        deleted_count = OrderItem.objects.filter(query).delete()[0]
        return JsonResponse({'Status': True, 'Deleted objects': deleted_count})

    @extend_schema(
        tags=['Basket'],
        summary='Update basket item quantities',
        request=BasketItemsSerializer,
        responses={200: StatusResponseSerializer},
    )
    def put(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        items_string = request.data.get('items')
        if not items_string:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        try:
            items_dict = items_string if isinstance(items_string, list) else load_json(items_string)
        except ValueError:
            return JsonResponse({'Status': False, 'Errors': 'Invalid request format'})

        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state='basket')
        objects_updated = 0
        for order_item in items_dict:
            if isinstance(order_item['id'], int) and isinstance(order_item['quantity'], int):
                objects_updated += OrderItem.objects.filter(
                    order_id=basket.id,
                    id=order_item['id'],
                ).update(quantity=order_item['quantity'])

        return JsonResponse({'Status': True, 'Updated objects': objects_updated})


class PartnerUpdate(APIView):
    """Запускает импорт прайса поставщика."""

    @extend_schema(
        tags=['Partner'],
        summary='Import supplier price list',
        request=PartnerImportSerializer,
        responses={200: MessageResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Only for shops'}, status=403)

        url = request.data.get('url')
        if not url:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        validate_url = URLValidator()
        try:
            validate_url(url)
        except ValidationError as error:
            return JsonResponse({'Status': False, 'Error': str(error)})

        execution = dispatch_task(do_import, url=url, user_id=request.user.id)
        if execution.queued:
            return JsonResponse({'Status': True, 'Message': 'Импорт запущен в фоне'})
        if isinstance(execution.result, str) and execution.result.startswith('Ошибка импорта:'):
            return JsonResponse({'Status': False, 'Errors': execution.result})
        return JsonResponse({'Status': True, 'Message': execution.result})


class PartnerState(APIView):
    """Читает или изменяет активное состояние магазина поставщика."""

    @extend_schema(tags=['Partner'], summary='Get partner shop state', responses={200: ShopSerializer})
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Only for shops'}, status=403)

        shop = Shop.objects.filter(user_id=request.user.id).first()
        if not shop:
            return partner_shop_missing_response()

        serializer = ShopSerializer(shop, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        tags=['Partner'],
        summary='Update partner shop state',
        request=PartnerStateUpdateSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Only for shops'}, status=403)

        state = request.data.get('state')
        if state is None:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        shop = Shop.objects.filter(user_id=request.user.id).first()
        if not shop:
            return partner_shop_missing_response()

        try:
            shop.state = strtobool(state)
        except ValueError as error:
            return JsonResponse({'Status': False, 'Errors': str(error)})

        shop.save(update_fields=['state'])
        return JsonResponse({'Status': True})


class PartnerOrders(APIView):
    """Возвращает заказы поставщика без черновиков корзины."""

    @extend_schema(tags=['Partner'], summary='List supplier orders', responses={200: OrderSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Only for shops'}, status=403)

        order = (
            Order.objects.filter(ordered_items__product_info__shop__user_id=request.user.id)
            .exclude(state='basket')
            .prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter',
            )
            .select_related('contact')
            .annotate(total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price')))
            .distinct()
        )

        serializer = OrderSerializer(order, many=True, context={'request': request})
        return Response(serializer.data)


class ContactView(APIView):
    """Управляет контактами доставки авторизованного пользователя."""

    @extend_schema(tags=['Contacts'], summary='List delivery contacts', responses={200: ContactSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        contact = Contact.objects.filter(user_id=request.user.id)
        serializer = ContactSerializer(contact, many=True, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        tags=['Contacts'],
        summary='Create a delivery contact',
        request=ContactSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if not {'city', 'street', 'phone'}.issubset(request.data):
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        try:
            request.data._mutable = True
        except AttributeError:
            pass

        request.data.update({'user': request.user.id})
        serializer = ContactSerializer(data=request.data)
        if not serializer.is_valid():
            return JsonResponse({'Status': False, 'Errors': serializer.errors})

        serializer.save()
        return JsonResponse({'Status': True})

    @extend_schema(
        tags=['Contacts'],
        summary='Delete delivery contacts',
        request=ContactDeleteSerializer,
        responses={200: StatusResponseSerializer},
    )
    def delete(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        items_string = request.data.get('items')
        if not items_string:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        items_list = [str(item) for item in items_string] if isinstance(items_string, list) else items_string.split(',')
        query = Q()
        objects_deleted = False
        for contact_id in items_list:
            if str(contact_id).isdigit():
                query |= Q(user_id=request.user.id, id=contact_id)
                objects_deleted = True

        if not objects_deleted:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        deleted_count = Contact.objects.filter(query).delete()[0]
        return JsonResponse({'Status': True, 'Deleted objects': deleted_count})

    @extend_schema(
        tags=['Contacts'],
        summary='Update a delivery contact',
        request=ContactSerializer,
        responses={200: StatusResponseSerializer},
    )
    def put(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if 'id' not in request.data or not str(request.data['id']).isdigit():
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        contact = Contact.objects.filter(id=request.data['id'], user_id=request.user.id).first()
        if not contact:
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        serializer = ContactSerializer(contact, data=request.data, partial=True)
        if not serializer.is_valid():
            return JsonResponse({'Status': False, 'Errors': serializer.errors})

        serializer.save()
        return JsonResponse({'Status': True})


class OrderView(APIView):
    """Читает оформленные заказы и переводит корзину в новый заказ."""

    @extend_schema(tags=['Orders'], summary='List user orders', responses={200: OrderSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        order = (
            Order.objects.filter(user_id=request.user.id)
            .exclude(state='basket')
            .prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter',
            )
            .select_related('contact')
            .annotate(total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price')))
            .distinct()
        )

        serializer = OrderSerializer(order, many=True, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        tags=['Orders'],
        summary='Place an order from basket',
        request=OrderCreateSerializer,
        responses={200: StatusResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if not {'id', 'contact'}.issubset(request.data):
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        if not str(request.data['id']).isdigit():
            return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})

        try:
            is_updated = Order.objects.filter(
                user_id=request.user.id,
                id=request.data['id'],
            ).update(
                contact_id=request.data['contact'],
                state='new',
            )
        except IntegrityError:
            return JsonResponse({'Status': False, 'Errors': 'Invalid arguments'})

        if is_updated:
            new_order.send(sender=self.__class__, user_id=request.user.id)
            return JsonResponse({'Status': True})

        return JsonResponse({'Status': False, 'Errors': 'Required arguments are missing'})


class SentryDebugView(APIView):
    """Принудительно вызывает исключение для проверки интеграции Sentry/Rollbar."""

    permission_classes = (IsAdminUser,)

    @extend_schema(
        tags=['Operations'],
        summary='Trigger a test exception',
        responses={500: StatusResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        raise RuntimeError('VoN debug exception endpoint')


class SocialTokenBridgeView(View):
    """Преобразует аутентифицированную Django-сессию в DRF-токен."""

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseRedirect(f'{settings.FRONTEND_URL}#social_error=unauthenticated')

        token, _ = Token.objects.get_or_create(user=request.user)
        return HttpResponseRedirect(f'{settings.FRONTEND_URL}#token={token.key}&auth=social')


class SocialAuthErrorRedirectView(View):
    """Возвращает пользователя в SPA после неудачной социальной аутентификации."""

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(f'{settings.FRONTEND_URL}#social_error=login_failed')
