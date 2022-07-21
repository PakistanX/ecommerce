import logging
import os

import waffle
from django.core.exceptions import MultipleObjectsReturned
from django.core.management import call_command
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.six import StringIO
from django.views.generic import View
from edx_rest_api_client.client import EdxRestApiClient
from edx_rest_api_client.exceptions import SlumberHttpBaseException
from oscar.apps.partner import strategy
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_class, get_model
from requests.exceptions import Timeout

from ecommerce.core.url_utils import get_lms_url
from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.offer.constants import DYNAMIC_DISCOUNT_FLAG
from ecommerce.extensions.payment.processors.easypaisa import EasyPaisa


logger = logging.getLogger(__name__)

Applicator = get_class('offer.applicator', 'Applicator')
Basket = get_model('basket', 'Basket')
BillingAddress = get_model('order', 'BillingAddress')
Country = get_model('address', 'Country')
NoShippingRequired = get_class('shipping.methods', 'NoShippingRequired')
OrderNumberGenerator = get_class('order.utils', 'OrderNumberGenerator')
OrderTotalCalculator = get_class('checkout.calculators', 'OrderTotalCalculator')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')


class EasyPaisaPostBackView(EdxOrderPlacementMixin, View):
    """Handle response from EasyPaisa API."""

    @property
    def payment_processor(self):
        return EasyPaisa(self.request.site)

    @method_decorator(transaction.non_atomic_requests)
    def dispatch(self, request, *args, **kwargs):
        return super(EasyPaisaPostBackView, self).dispatch(request, *args, **kwargs)

    def _get_basket(self, payment_id):
        """
        Retrieve a basket using a payment ID.

        Arguments:
            payment_id: payment_id received from EasyPaisa.

        Returns:
            It will return related basket or log exception and return None if
            duplicate payment_id received or any other exception occurred.

        """
        try:
            basket = PaymentProcessorResponse.objects.get(
                processor_name=self.payment_processor.NAME,
                transaction_id=payment_id
            ).basket
            basket.strategy = strategy.Default()
            basket_add_organization_attribute(basket, self.request.GET)
            return basket
        except MultipleObjectsReturned:
            logger.warning(u"Duplicate payment ID [%s] received from EasyPaisa.", payment_id)
            return None
        except Exception:  # pylint: disable=broad-except
            logger.exception(u"Unexpected error during basket retrieval while executing PayPal payment.")
            return None

    def get(self, request):
        """Handle an incoming user returned to us by EasyPaisa after approving payment."""
        logger.info('\n\n\n{}\n\n\n'.format(request.GET))
        # payment_id = request.GET.get('paymentId')
        # payer_id = request.GET.get('PayerID')
        # logger.info(u"Payment [%s] approved by payer [%s]", payment_id, payer_id)
        #
        # paypal_response = request.GET.dict()
        # basket = self._get_basket(payment_id)
        #
        # if not basket:
        #     return redirect(self.payment_processor.error_url)
        #
        # receipt_url = get_receipt_page_url(
        #     order_number=basket.order_number,
        #     site_configuration=basket.site.siteconfiguration,
        #     disable_back_button=True,
        # )
        #
        # try:
        #     with transaction.atomic():
        #         try:
        #             self.handle_payment(paypal_response, basket)
        #         except PaymentError:
        #             return redirect(self.payment_processor.error_url)
        # except:  # pylint: disable=bare-except
        #     logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
        #     return redirect(receipt_url)
        #
        # try:
        #     order = self.create_order(request, basket)
        # except Exception:  # pylint: disable=broad-except
        #     # any errors here will be logged in the create_order method. If we wanted any
        #     # Paypal specific logging for this error, we would do that here.
        #     return redirect(receipt_url)
        #
        # try:
        #     self.handle_post_order(order)
        # except Exception:  # pylint: disable=broad-except
        #     self.log_order_placement_exception(basket.order_number, basket.id)
        #
        # return redirect(receipt_url)

    def post(self, request):
        logger.info('\n\n\n{}\n\n\n'.format(request.POST))
