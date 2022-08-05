import logging

from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.generic import View
from oscar.apps.partner import strategy
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_class, get_model
from rest_framework.views import APIView
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.response import Response

from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.processors.postex import PostEx

logger = logging.getLogger(__name__)
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')


class PostExPaymentResponse(EdxOrderPlacementMixin):
    """Parent class for handling PostEx payment response."""

    @property
    def payment_processor(self):
        return PostEx(self.request.site)

    @method_decorator(transaction.non_atomic_requests)
    def dispatch(self, request, *args, **kwargs):
        return super(PostExPaymentResponse, self).dispatch(request, *args, **kwargs)

    def _get_basket(self, payment_id):
        """
        Retrieve a basket using a payment ID.

        Arguments:
            payment_id: payment_id received from PostEx.

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
            logger.warning(u"Duplicate payment ID [%s] received from PostEx.", payment_id)
            return None
        except Exception:  # pylint: disable=broad-except
            logger.exception(u"Unexpected error during basket retrieval while executing PostEx payment.")
            return None


class PostExPostBackAPI(PostExPaymentResponse, APIView):
    """Handle response from PostEx API."""

    authentication_classes = ()

    def process(self, request):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack response{}'.format(request.data))
        logger.info(request.META.get('REMOTE_ADDR'))
        logger.info(request.META.get('HTTP_X_FORWARDED_FOR'))
        payment_id = request.data.get('orderRefNumber')
        postex_response = request.data
        logger.info(self.payment_processor.configuration)

        self.payment_processor.record_processor_response(
            {
                'response': postex_response,
                'remote': request.META.get('REMOTE_ADDR'),
                'fowarded': request.META.get('HTTP_X_FORWARDED_FOR'),
                'host': request.META.get('HTTP_HOST'),
            },
            transaction_id=payment_id,
        )

        if request.META.get('HTTP_HOST') != self.payment_processor.configuration['domain']:
            return Response(HTTP_403_FORBIDDEN)

        basket = self._get_basket(payment_id)
        response = Response(HTTP_200_OK)

        if not basket:
            logger.error('Basket not found for {}'.format(postex_response))
            return response

        receipt_url = get_receipt_page_url(
            order_number=basket.order_number,
            site_configuration=basket.site.siteconfiguration,
            disable_back_button=True,
        )

        try:
            with transaction.atomic():
                try:
                    self.handle_payment(postex_response, basket)
                except PaymentError:
                    logger.error('Payment error in processing {}'.format(postex_response))
                    return response
        except:  # pylint: disable=bare-except
            logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
            return response

        try:
            order = self.create_order(request, basket)
        except Exception:  # pylint: disable=broad-except
            logger.warning('Exception in create order for {}'.format(postex_response))
            return response

        try:
            self.handle_post_order(order)
        except Exception:  # pylint: disable=broad-except
            self.log_order_placement_exception(basket.order_number, basket.id)

        return response

    def get(self, request):
        logger.info('Received GET request.')
        self.process(request)

    def post(self, request):
        logger.info('Received POST request.')
        self.process(request)


class PostExPostBackView(EdxOrderPlacementMixin, View):
    """Receipt redirection."""

    def get(self, request):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack response{}'.format(request.GET))
        payment_id = request.POST.get('orderRefNumber')
        postex_response = request.POST.dict()
        basket = self._get_basket(payment_id)

        if not basket:
            return redirect(self.payment_processor.error_url)

        receipt_url = get_receipt_page_url(
            order_number=basket.order_number,
            site_configuration=basket.site.siteconfiguration,
            disable_back_button=True,
        )

        try:
            with transaction.atomic():
                try:
                    self.handle_payment(postex_response, basket)
                except PaymentError:
                    return redirect(self.payment_processor.error_url)
        except:  # pylint: disable=bare-except
            logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
            return redirect(receipt_url)

        try:
            order = self.create_order(request, basket)
        except Exception:  # pylint: disable=broad-except
            return redirect(receipt_url)

        try:
            self.handle_post_order(order)
        except Exception:  # pylint: disable=broad-except
            self.log_order_placement_exception(basket.order_number, basket.id)

        return redirect(receipt_url)
