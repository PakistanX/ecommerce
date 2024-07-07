import hashlib
import hmac
import json
import logging
from collections import OrderedDict

import requests

from django.http import HttpResponseBadRequest
from ecommerce.extensions.api.serializers import PaymentPostBackSerializer
from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.processors.xstack import XStack
from oscar.core.loading import get_model
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')

def _get_basket(request, basket_id):
        """
        Retrieve a basket using a basket ID.
        """
        try:
            basket = request.user.baskets.get(id=basket_id)
        except Exception:  # pylint: disable=broad-except
            logger.exception(u"Unexpected error during basket retrieval while executing PostEx COD transaction.")
            return None
        basket.strategy = request.strategy
        basket_add_organization_attribute(basket, request.GET)
        basket.freeze()

        return basket

class XStackPostBackView(APIView):
    """Xstack payment intent"""

    @property
    def payment_processor(self):
        return XStack(self.request.site)
   
    def post(self, request):
        """
        This creates a payment intent , manages order and basket status,
        creates receipt url that is then shown to user
        """
        secret_key = self.payment_processor.configuration['secret_key']
        hmac_secret = self.payment_processor.configuration['hmac_secret']
        account_id = self.payment_processor.configuration['account_id']
        data = PaymentPostBackSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        basket = _get_basket(request, request.data.get('basket_id'))
        if not basket:
            logger.exception('Basket not found for ID {}'.format(request.data.get('basket_id')))
            return HttpResponseBadRequest('Unable to find linked basket')

        payload = OrderedDict([
            ('amount', int(float(basket.total_incl_tax))),
            ('currency', "PKR"),
            ('payment_method_types', "card"),
            ('customer', OrderedDict([
                ('email', data.data['email']),
                ('name', '{} {}'.format(data.data['first_name'], data.data['last_name'])),
                ('phone', data.data['phone_number']),
            ])),
            ('shipping', OrderedDict([
                ('address1', '{}, {}'.format(data.data['street_address'], data.data['address_line2'])),
                ('city', data.data['city']),
                ('country', data.data['country']),
                ('province', data.data['state']),
                ('zip', data.data['post_code'])
            ])),
            ("metadata", OrderedDict([('order_reference', "{}-{}".format(request.user.id, basket.order_number))]))
        ])

        json_body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        signature = hmac.new(hmac_secret.encode('utf-8'), json_body, hashlib.sha256).hexdigest()
        headers = {
            "x-api-key": secret_key,
            "Content-Type": "application/json",
            "x-signature": signature,
            "x-account-id": account_id,
        }
        payment_intent_create_res = requests.post(
            self.payment_processor.configuration['payment_intent_create_url'],
            data=json_body,
            headers=headers,
        )
        payment_intent_create_res = payment_intent_create_res.json()

        try:
            if payment_intent_create_res['responseStatus'] == 'OK':
                return Response(
                    data={
                        'encryptionKey':payment_intent_create_res['data']['encryptionKey'],
                        'clientSecret':payment_intent_create_res['data']['pi_client_secret'],
                        'paymentIntentId':payment_intent_create_res['data']['_id'],
                    },
                    status=HTTP_200_OK
                )
        except Exception as e:
            logger.exception('Failed to create xstack payment intent {}, response {}.', basket.order_number, payment_intent_create_res)
            return HttpResponseBadRequest('Some error occurred during payment intent creation, '+payment_intent_create_res['message'])

class XStackOrderCompletionView(EdxOrderPlacementMixin, APIView):

    @property
    def payment_processor(self):
        return XStack(self.request.site)

    @staticmethod
    def _send_email(user, course_key, site_configuration):
        """Send email notification to learner after enrollment."""
        api_url = site_configuration.commerce_api_client
        logger.info('username:{} course_key:{}'.format(user, course_key))
        try:
            api_resource_name = 'enrollment_mail/{}/{}'.format(user, course_key)
            endpoint = getattr(api_url, api_resource_name)
            endpoint().get()
        except Exception:  # pylint: disable=broad-except
            logger.exception('Failed to send enrollment notification for [%s] [%s] from LMS.', user, course_key)

    def post(self, request):
        payment_intent_id = request.data.get('payment_intent_id')
        basket_id = request.data.get('basket_id')

        basket = _get_basket(request, basket_id)
        if not basket:
            logger.exception('Basket not found for ID {}'.format(basket_id))
            return HttpResponseBadRequest('Unable to find linked basket')

        headers = {
            "x-api-key": self.payment_processor.configuration['secret_key'],
            "x-account-id": self.payment_processor.configuration['account_id'],
        }
        payment_intent_retrieve_res = requests.get(
            self.payment_processor.configuration['payment_intent_retrieve_url']+payment_intent_id,
            headers=headers,
        )
        payment_intent_retrieve_res = payment_intent_retrieve_res.json()

        try:
            self.handle_payment(
                response={
                    'payment_intent_response': payment_intent_retrieve_res,
                    'remote': request.META.get('REMOTE_ADDR'),
                    'fowarded': request.META.get('HTTP_X_FORWARDED_FOR'),
                    'host': request.META.get('HTTP_HOST'),
                },
                basket=basket,
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.info('Payment error in processing {}'.format(basket_id))
            return HttpResponseBadRequest(str(e))

        try:
            order = self.create_order(request, basket)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning('Exception in create order for {}'.format(basket_id))
            return HttpResponseBadRequest(str(e))

        try:
            self.handle_post_order(order)
        except Exception:  # pylint: disable=broad-except
            self.log_order_placement_exception(basket.order_number, basket.id)

        self._send_email(basket.owner.username, basket.all_lines()[0].product.course.id, request.site.siteconfiguration)
        receipt_url = get_receipt_page_url(
            order_number=basket.order_number,
            site_configuration=basket.site.siteconfiguration,
            disable_back_button=True,
        )
        return Response(
            data={
                'receipt_url':receipt_url,
            },
            status=HTTP_200_OK
        )
