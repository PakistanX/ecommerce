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

    def process(self, request):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack response{}'.format(request.query_params))

        postex_response = request.query_params.dict()
        payment_id = postex_response.get('orderRefNum')

        self.payment_processor.record_processor_response(
            {
                'response': postex_response,
                'remote': request.META.get('REMOTE_ADDR'),
                'fowarded': request.META.get('HTTP_X_FORWARDED_FOR'),
                'host': request.META.get('HTTP_HOST'),
            },
            transaction_id='PostEx for {}'.format(payment_id),
        )

        basket = self._get_basket(payment_id)
        response = Response(HTTP_200_OK)

        self._send_email(basket.owner.username, basket.all_lines()[0].product.course.id, request.site.siteconfiguration)

        if request.META.get('HTTP_HOST') != self.payment_processor.configuration['domain']:
            return Response(HTTP_403_FORBIDDEN)

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

        self._send_email(basket.owner.username, basket.all_lines()[0].product.course.id, request.site.siteconfiguration)
        return response

    def get(self, request):
        """Handle GET request for PostEx IPN."""
        logger.info('Received GET request.')
        return self.process(request)

    def post(self, request):
        """Handle POST request for PostEx IPN."""
        logger.info('Received POST request.')
        return self.process(request)


class PostExPostBackView(EdxOrderPlacementMixin, View):
    """Receipt redirection."""

    def get(self, request):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack response after button click')
        # TODO: Write logic for verifying payment using order_id and then redirecting learner to error/receipt page.
        return redirect(self.payment_processor.error_url)
