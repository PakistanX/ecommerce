import json
import logging

from django.http import HttpResponseBadRequest
import requests

from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.generic import View
from ecommerce.extensions.api.serializers import PaymentPostBackSerializer
from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.processors.postex import PostEx, PostExCOD
from ecommerce.extensions.payment.tasks import trigger_active_campaign_event
from oscar.apps.partner import strategy
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_model
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.views import APIView

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

    def send_error_response(self, basket):
        if basket:
            trigger_active_campaign_event.delay(
                'payment_unsuccessful_view', basket.owner.email, basket.all_lines()[0].product.course.id
            )
        return self.error_response

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
            return self.send_error_response(basket)

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
                    logger.info('Payment error in processing {}'.format(postex_response))
                    return self.send_error_response(basket)
        except:  # pylint: disable=bare-except
            logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
            return self.send_error_response(basket)

        try:
            order = self.create_order(request, basket)
        except Exception:  # pylint: disable=broad-except
            logger.warning('Exception in create order for {}'.format(postex_response))
            return self.send_error_response(basket)

        try:
            self.handle_post_order(order)
        except Exception:  # pylint: disable=broad-except
            trigger_active_campaign_event.delay(
                'payment_unsuccessful_view', basket.owner.email, basket.all_lines()[0].product.course.id
            )
            self.log_order_placement_exception(basket.order_number, basket.id)

        self._send_email(basket.owner.username, basket.all_lines()[0].product.course.id, request.site.siteconfiguration)
        trigger_active_campaign_event.delay(
            'payment_successful_view', basket.owner.email, basket.all_lines()[0].product.course.id
        )
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
        return redirect(receipt_url) if postex_response['status'] != '500' else self.send_error_response(basket)

    def get(self, request):
        """Handle an incoming user returned to us by PostEx after approving payment."""
        logger.info('PostEx postBack redirection')
        return self.start_processing_payment(request, request.GET.dict())


class PostExCODPaymentView(EdxOrderPlacementMixin, APIView):
    """Receipt redirection and postex cod payment intent"""

    @property
    def payment_processor(self):
        return PostExCOD(self.request.site)
    
    @staticmethod
    def _send_email(tracking_id, user, course_key, site_configuration):
        """
        Send email notification to learner after order with tracking ID.
        """
        api_url = site_configuration.commerce_api_client
        logger.info('username:{} course_key:{}'.format(user, course_key))
        try:
            api_resource_name = 'cod_order_mail/{}/{}/{}'.format(user, course_key, tracking_id)
            endpoint = getattr(api_url, api_resource_name)
            endpoint().get()
        except Exception:  # pylint: disable=broad-except
            logger.exception('Failed to send Postex COD order confirmation notification for [%s] [%s].', user, course_key)

    def _get_basket(self, request, basket_id):
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
    
    @staticmethod
    def _get_courseid_title(line):
        """
        Get CourseID & Title from basket ite
        """
        courseid = ''
        line_course = line.product.course
        if line_course:
            courseid = "{}|".format(line_course.id)
        return courseid + line.product.title

    def post(self, request):
        """
        This creates a payment intent, manages order and basket status,
        creates receipt url that is then shown to user
        """
        api_url = self.payment_processor.configuration['create_order_url']
        api_key = self.payment_processor.configuration['key']
        pickup_address_code = self.payment_processor.configuration['pickup_address_code']
        fixed_delivery_charges = self.payment_processor.configuration['fixed_delivery_charges']
        data = PaymentPostBackSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        basket_id = request.data.get('basket_id')

        basket = self._get_basket(request, basket_id)
        if not basket:
            logger.exception('Basket not found for ID {}'.format(basket_id))
            return HttpResponseBadRequest('Unable to find linked basket')

        address = '{}, {}, {}, {} - {}'.format(
            data.data['address'],
            data.data['city'],
            data.data['state'],
            data.data['country'],
            str(data.data['post_code']))

        payload = json.dumps({
            "cityName": data.data['city'],
            "customerName": data.data['fullname'],
            "customerPhone": data.data['phone_number'],
            "deliveryAddress": address,
            "invoiceDivision": 0,
            "invoicePayment": int(float(basket.total_incl_tax)) + int(fixed_delivery_charges),
            "items": 1,
            "orderRefNumber": basket.order_number,
            "orderType": "Normal",
            "pickupAddressCode": pickup_address_code,
            'orderDetail': self._get_courseid_title(basket.all_lines()[0]),
        })

        headers = {
            "token": api_key,
            "Content-Type": "application/json",
        }
        payment_intent_res = requests.post(api_url, data=payload, headers=headers)
        payment_intent_res = payment_intent_res.json()

        try:
            self.handle_payment(
                response={
                    'data': data.data,
                    'pickup_address': address,
                    'payment_intent_response': payment_intent_res,
                    'remote': request.META.get('REMOTE_ADDR'),
                    'fowarded': request.META.get('HTTP_X_FORWARDED_FOR'),
                    'host': request.META.get('HTTP_HOST'),
                },
                basket=basket)
        except Exception as e:  # pylint: disable=broad-except
            logger.info('Payment error in processing {}'.format(basket_id))
            return HttpResponseBadRequest(str(e))
        
        try:
            self.create_order(request, basket, payment_processor='postex_cod')
        except Exception as e:  # pylint: disable=broad-except
            logger.warning('Exception in create order for {}'.format(basket_id))
            return HttpResponseBadRequest(str(e))

        tracking_id = payment_intent_res.get('dist').get('trackingNumber')
        self._send_email(tracking_id, basket.owner.username, basket.all_lines()[0].product.course.id, request.site.siteconfiguration)

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
