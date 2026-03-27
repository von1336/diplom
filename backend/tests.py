from unittest import mock

from django.test import SimpleTestCase, TestCase
from kombu.exceptions import OperationalError
from rest_framework.authtoken.models import Token

from backend.models import User
from backend.tasks import dispatch_task


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
