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

    def start_processing_payment(self, request, postex_response):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack response{}'.format(postex_response))
        payment_id = postex_response.get('orderRefNum')

        self.payment_processor.record_processor_response(
            {
                'response': postex_response,
                'remote': request.META.get('REMOTE_ADDR'),
                'fowarded': request.META.get('HTTP_X_FORWARDED_FOR'),
                'host': request.META.get('HTTP_HOST'),
            },
            transaction_id=self.processor_message.format(payment_id),
        )

        if not self.is_verified_ip_address(request):
            return self.forbidden_response

        basket = self._get_basket(payment_id)

        if not basket:
            logger.error('Basket not found for {}'.format(postex_response))
            return self.error_response

        return self.process_payment(basket, request, postex_response)


class PostExPostBackAPI(PostExPaymentResponse, APIView):
    """Handle response from PostEx API."""

    authentication_classes = ()
    processor_message = 'PostEx IPN for {}'

    def is_verified_ip_address(self, request):
        """Check if the IP address of client matches PostEx."""
        return request.META.get('HTTP_X_FORWARDED_FOR') in self.payment_processor.configuration['domains']

    @property
    def error_response(self):
        """Error response is 200 because this is being sent to PostEx."""
        return Response(status=HTTP_200_OK)

    @property
    def forbidden_response(self):
        """Forbidden response for invalid hosts."""
        return Response(status=HTTP_403_FORBIDDEN)

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

    def process_payment(self, basket, request, postex_response):
        """Process payment and enroll user in course."""

        try:
            with transaction.atomic():
                try:
                    self.handle_payment(postex_response, basket)
                except PaymentError:
                    logger.error('Payment error in processing {}'.format(postex_response))
                    return self.error_response
        except:  # pylint: disable=bare-except
            logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
            return self.error_response

        try:
            order = self.create_order(request, basket)
        except Exception:  # pylint: disable=broad-except
            logger.warning('Exception in create order for {}'.format(postex_response))
            return self.error_response

        try:
            self.handle_post_order(order)
        except Exception:  # pylint: disable=broad-except
            self.log_order_placement_exception(basket.order_number, basket.id)

        self._send_email(basket.owner.username, basket.all_lines()[0].product.course.id, request.site.siteconfiguration)
        return self.error_response

    def get(self, request):
        """Handle GET request for PostEx IPN."""
        logger.info('Received GET request.')
        return self.start_processing_payment(request, request.query_params.dict())

    def post(self, request):
        """Handle POST request for PostEx IPN."""
        logger.info('Received POST request.')
        return self.start_processing_payment(request, request.query_params.dict())


class PostExPostBackView(PostExPaymentResponse, View):
    """Receipt redirection."""

    processor_message = 'PostEx Redirection for {}'

    def is_verified_ip_address(self, request):
        """We do not need to identify IP address for views."""
        return True

    @property
    def error_response(self):
        """Error page redirection."""
        return redirect(self.payment_processor.error_url)

    def process_payment(self, basket, request, postex_response):
        """Process payment redirect user to success or error page."""
        receipt_url = get_receipt_page_url(
            order_number=basket.order_number,
            site_configuration=basket.site.siteconfiguration,
            disable_back_button=True,
        )
        return redirect(receipt_url) if postex_response['status'] != '500' else self.error_response

    def get(self, request):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack redirection')
        return self.start_processing_payment(request, request.GET.dict())
