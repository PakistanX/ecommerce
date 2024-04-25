import hashlib
import hmac
import json
import logging
from collections import OrderedDict

import requests
from django.core.exceptions import MultipleObjectsReturned
from oscar.apps.partner import strategy
from oscar.core.loading import get_class, get_model
from ecommerce.extensions.api.serializers import XStackPostBackSerializer
from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.processors.xstack import XStack
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST,HTTP_200_OK
from rest_framework.views import APIView
from oscar.apps.payment.exceptions import PaymentError

logger = logging.getLogger(__name__)
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')

class XStackPostBackView(EdxOrderPlacementMixin, APIView):
    """Receipt redirection and xstack payment intent"""

    processor_message = 'XStack payment intent for {}'

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

    def _get_basket(self, payment_id):
        """
        Retrieve a basket using a payment ID.

        Arguments:
            payment_id: payment_id received from payment intent url generated by xstack payment processor.

        Returns:
            It will return related basket or log exception and return None if
            duplicate payment_id received or any other exception occurred.

        """
        try:
            basket = PaymentProcessorResponse.objects.get(
                processor_name=self.payment_processor.NAME,
                transaction_id=payment_id
            ).basket
        except MultipleObjectsReturned:
            logger.warning(u"Duplicate payment ID [%s] received from PostEx.", payment_id)

            if 'Redirection' not in self.processor_message:
                return None

            logger.info('Looking into multiple baskets for view')
            basket = PaymentProcessorResponse.objects.filter(
                processor_name=self.payment_processor.NAME,
                transaction_id=payment_id
            )[0].basket
        except Exception:  # pylint: disable=broad-except
            logger.exception(u"Unexpected error during basket retrieval while executing PostEx payment.")
            return None

        basket.strategy = strategy.Default()
        basket_add_organization_attribute(basket, self.request.GET)
        return basket

    def post(self, request):
        """
        This creates a payment intent , manages order and basket status,
        creates and reciept url that is then shown to user
        """
        secret_key = self.payment_processor.configuration['secret_key']
        hmac_secret = self.payment_processor.configuration['hmac_secret']
        account_id = self.payment_processor.configuration['account_id']
        data = XStackPostBackSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        basket_res = request.GET.dict()
        payment_id = basket_res['orderRefNum']
        payload = OrderedDict([
            ('amount', 10),
            ('currency', "PKR"),
            ('payment_method_types', "card"),
            ('customer', OrderedDict([
                ('email', "hjj@hh.cc"),
                ('name', "jjj"),
                ('phone', "876876"),
            ])),
            ('shipping', OrderedDict([
                ('address1', "kjhkj"),
                ('city', "kjhkj"),
                ('country', "kjhkj"),
                ('province', "79"),
                ('zip', "987")
            ])),
            ("metadata", OrderedDict([('order_reference', payment_id)]))
        ])

        json_body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        signature = hmac.new(hmac_secret.encode('utf-8'), json_body, hashlib.sha256).hexdigest()
        headers = {
            "x-api-key": secret_key,
            "Content-Type": "application/json",
            "x-signature": signature,
            "x-account-id": account_id,
        }
        payment_intent_res = requests.post(
            self.payment_processor.configuration['payment_intent_url'],
            data=json_body,
            headers=headers
        )
        basket_res['status'] = payment_intent_res.status_code
        payment_intent_res = payment_intent_res.json()
        self.payment_processor.record_processor_response(
            {
                'response': basket_res,
                'remote': request.META.get('REMOTE_ADDR'),
                'fowarded': request.META.get('HTTP_X_FORWARDED_FOR'),
                'host': request.META.get('HTTP_HOST'),
            },
            transaction_id=self.processor_message.format(payment_id)
        )
        basket = self._get_basket(payment_id)
        if not basket:
            logger.error('Basket not found for {}'.format(basket_res))
            return Response(status=HTTP_400_BAD_REQUEST)

        try:
            self.handle_payment(basket_res, basket)
        except PaymentError:
            logger.info('Payment error in processing {}'.format(basket_res))
            return Response(status=HTTP_400_BAD_REQUEST)

        try:
            order = self.create_order(request, basket)
        except Exception:  # pylint: disable=broad-except
            logger.warning('Exception in create order for {}'.format(basket_res))
            return Response(status=HTTP_400_BAD_REQUEST)

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
                'encryptionKey':payment_intent_res['data']['encryptionKey'],
                'clientSecret':payment_intent_res['data']['pi_client_secret']
            },
            status=HTTP_200_OK
        )
