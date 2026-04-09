import tempfile
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from kombu.exceptions import OperationalError
from rest_framework.authtoken.models import Token
from social_core.pipeline.social_auth import associate_by_email

from backend.models import Category, Product, ProductInfo, Shop, User
from backend.social_pipeline import activate_social_user
from backend.tasks import dispatch_task, do_import, generate_thumbnails


TEST_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!'
    b'\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00'
    b'\x00\x02\x02D\x01\x00;'
)


class TaskDispatchTests(SimpleTestCase):
    def test_dispatch_task_falls_back_to_sync_when_broker_is_unavailable(self):
        task = mock.Mock()
        task.name = 'backend.tests.fake_task'
        task.delay.side_effect = OperationalError('redis down')
        task.return_value = 'done'

        execution = dispatch_task(task, user_id=1)

        self.assertFalse(execution.queued)
        self.assertEqual(execution.result, 'done')
        task.assert_called_once_with(user_id=1)


class ImportTaskTests(TestCase):
    @mock.patch('backend.tasks.safe_load')
    @mock.patch('backend.tasks.requests.get')
    def test_do_import_uses_timeout_raise_for_status_and_safe_loader(self, mock_get, mock_safe_load):
        user = User.objects.create_user(
            email='supplier@example.com',
            password='StrongPass123!',
            first_name='Supplier',
            last_name='Owner',
            company='Supplier Co',
            position='Owner',
            type='shop',
            is_active=True,
        )
        response = mock.Mock()
        response.content = b'yaml-content'
        mock_get.return_value = response
        mock_safe_load.return_value = {
            'shop': 'Test Shop',
            'categories': [{'id': 1, 'name': 'Phones'}],
            'goods': [
                {
                    'id': 101,
                    'name': 'iPhone',
                    'category': 1,
                    'model': '15 Pro',
                    'price': 100000,
                    'price_rrc': 110000,
                    'quantity': 3,
                    'parameters': {'color': 'black'},
                }
            ],
        }

        result = do_import.run('https://example.com/price.yml', user.id)

        mock_get.assert_called_once_with('https://example.com/price.yml', timeout=10)
        response.raise_for_status.assert_called_once_with()
        mock_safe_load.assert_called_once_with(b'yaml-content')
        self.assertTrue(result.startswith('Импорт завершён:'))
        self.assertEqual(ProductInfo.objects.count(), 1)


class AccountApiTests(TestCase):
    def test_register_keeps_shop_type_without_redis(self):
        response = self.client.post('/api/v1/user/register', {
            'first_name': 'Shop',
            'last_name': 'Owner',
            'email': 'shop@example.com',
            'password': 'StrongPass123!',
            'company': 'Shop Co',
            'position': 'Owner',
            'type': 'shop',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'Status': True})
        self.assertEqual(User.objects.get(email='shop@example.com').type, 'shop')

    def test_partner_state_returns_404_when_shop_is_missing(self):
        user = User.objects.create_user(
            email='supplier@example.com',
            password='StrongPass123!',
            first_name='Supplier',
            last_name='Owner',
            company='Supplier Co',
            position='Owner',
            type='shop',
            is_active=True,
        )
        token, _ = Token.objects.get_or_create(user=user)

        response = self.client.get(
            '/api/v1/partner/state',
            HTTP_AUTHORIZATION=f'Token {token.key}',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['Status'], False)

    def test_login_is_throttled_after_rate_limit(self):
        user = User.objects.create_user(
            email='buyer@example.com',
            password='StrongPass123!',
            first_name='Buyer',
            last_name='User',
            company='Buyer Co',
            position='Manager',
            type='buyer',
            is_active=True,
        )
        cache.clear()

        for _ in range(5):
            response = self.client.post('/api/v1/user/login', {
                'email': user.email,
                'password': 'StrongPass123!',
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['Status'])

        throttled_response = self.client.post('/api/v1/user/login', {
            'email': user.email,
            'password': 'StrongPass123!',
        })

        self.assertEqual(throttled_response.status_code, 429)


class SocialAuthTests(TestCase):
    def test_social_token_bridge_returns_token_fragment(self):
        user = User.objects.create_user(
            email='social@example.com',
            password='StrongPass123!',
            first_name='Social',
            last_name='User',
            company='VoN',
            position='Buyer',
            is_active=True,
        )
        self.client.force_login(user)

        response = self.client.get('/auth/token-bridge/')

        token = Token.objects.get(user=user)
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'#token={token.key}&auth=social', response['Location'])

    def test_associate_by_email_matches_existing_user(self):
        user = User.objects.create_user(
            email='existing@example.com',
            password='StrongPass123!',
            first_name='Existing',
            last_name='Buyer',
            company='VoN',
            position='Buyer',
            is_active=False,
        )
        backend = mock.Mock()
        backend.strategy.storage.user.get_users_by_email.return_value = [user]

        result = associate_by_email(backend, {'email': user.email})

        self.assertIn('social_core.pipeline.social_auth.associate_by_email', settings.SOCIAL_AUTH_PIPELINE)
        self.assertEqual(result['user'], user)
        self.assertFalse(result['is_new'])
        self.assertEqual(User.objects.filter(email=user.email).count(), 1)

    def test_social_pipeline_activates_user_and_sets_username(self):
        user = User.objects.create_user(
            email='pipeline@example.com',
            password='StrongPass123!',
            first_name='Pipeline',
            last_name='User',
            company='VoN',
            position='Buyer',
            is_active=False,
        )
        user.username = ''
        user.save(update_fields=['username'])

        activate_social_user(backend=mock.Mock(), user=user, is_new=True)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.username, user.email)


class CatalogCachingTests(TestCase):
    def test_products_endpoint_serves_cached_payload_on_repeat_request(self):
        cache.clear()
        category = Category.objects.create(name='Phones')
        shop = Shop.objects.create(name='Main Shop', state=True)
        product = Product.objects.create(name='Phone', category=category)
        ProductInfo.objects.create(
            product=product,
            shop=shop,
            external_id=1,
            model='X',
            quantity=5,
            price=100,
            price_rrc=120,
        )

        first_response = self.client.get('/api/v1/products')
        self.assertEqual(first_response.status_code, 200)
        first_payload = first_response.json()

        with mock.patch('backend.views.ProductInfo.objects.filter', side_effect=AssertionError('database should not be queried')):
            second_response = self.client.get('/api/v1/products')

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json(), first_payload)


class AdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            company='VoN',
            position='Admin',
        )

    def test_admin_index_loads_with_baton_enabled(self):
        self.client.force_login(self.admin_user)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'VoN')

    def test_shop_import_page_loads(self):
        self.client.force_login(self.admin_user)

        response = self.client.get('/admin/backend/shop/import/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Импорт прайса поставщика')


class MediaSignalTests(TestCase):
    def test_user_avatar_save_dispatches_thumbnail_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                avatar = SimpleUploadedFile('avatar.gif', TEST_GIF, content_type='image/gif')
                with mock.patch('backend.signals.dispatch_task') as mock_dispatch:
                    User.objects.create_user(
                        email='avatar@example.com',
                        password='StrongPass123!',
                        first_name='Avatar',
                        last_name='User',
                        company='VoN',
                        position='Buyer',
                        is_active=True,
                        avatar=avatar,
                    )

                self.assertTrue(
                    any(
                        call.args[0] is generate_thumbnails and call.kwargs.get('model_name') == 'User'
                        for call in mock_dispatch.call_args_list
                    )
                )

    def test_product_image_save_dispatches_thumbnail_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                category = Category.objects.create(name='Photo')
                image = SimpleUploadedFile('product.gif', TEST_GIF, content_type='image/gif')
                with mock.patch('backend.signals.dispatch_task') as mock_dispatch:
                    Product.objects.create(name='Camera', category=category, image=image)

                self.assertTrue(
                    any(
                        call.args[0] is generate_thumbnails and call.kwargs.get('model_name') == 'Product'
                        for call in mock_dispatch.call_args_list
                    )
                )


class SentryTests(TestCase):
    def test_debug_endpoint_denies_non_admin(self):
        user = User.objects.create_user(
            email='buyer2@example.com',
            password='StrongPass123!',
            first_name='Buyer',
            last_name='User',
            company='VoN',
            position='Buyer',
            is_active=True,
        )
        token, _ = Token.objects.get_or_create(user=user)

        response = self.client.get('/api/v1/debug/sentry', HTTP_AUTHORIZATION=f'Token {token.key}')

        self.assertEqual(response.status_code, 403)

    def test_debug_endpoint_raises_for_admin(self):
        admin_user = User.objects.create_superuser(
            email='admin2@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            company='VoN',
            position='Admin',
        )
        token, _ = Token.objects.get_or_create(user=admin_user)

        with self.assertRaises(RuntimeError):
            self.client.get('/api/v1/debug/sentry', HTTP_AUTHORIZATION=f'Token {token.key}')
