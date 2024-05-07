""" PostEx payment processing. """
from __future__ import absolute_import, unicode_literals

import logging
from collections import OrderedDict
from urllib.parse import urlencode

from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse

logger = logging.getLogger(__name__)

#TODO: Fix logs
class XStack(BasePaymentProcessor):
    """XStack API implementation."""

    NAME = 'xstack'

    def __init__(self, site):
        """
        Constructs a new instance of the XStack payment processor.

        Raises:
            KeyError: If a required setting is not configured for this payment processor
        """
        super(XStack, self).__init__(site)

    @staticmethod
    def get_courseid_title(line):
        """
        Get CourseID & Title from basket item

        Arguments:
            line: basket item

        Returns:
             Concatenated string containing course id & title if exists.
        """
        courseid = ''
        line_course = line.product.course
        if line_course:
            courseid = "{}|".format(line_course.id)
        return courseid + line.product.title

    @staticmethod
    def create_ordered_dict(data):
        """Create ordered dict from list of tuples."""
        ordered_data = OrderedDict()
        for key, value in data:
            ordered_data[key] = value
        return ordered_data

    def get_transaction_parameters(self, basket, request=None, use_client_side_checkout=False, **kwargs):
        """
        Create a new XStack Intent api url.

        Arguments:
            basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which is used to construct PayPal's `return_url`.
            use_client_side_checkout (bool, optional): This value is not used.
            **kwargs: Additional parameters; not used by this method.

        Returns:
            dict: XStack-specific parameters required to complete a transaction. Must contain a URL
                to which users can be directed in order to approve a newly created payment.
        """
        logger.info('Starting xstack payment url creation')
        order_id = basket.order_number
        amount = basket.total_incl_tax
        user_name = basket.owner.username
        data = self.create_ordered_dict([
            ('customerName', user_name),
            ('amount', amount),
            ('orderRefNum', order_id),
        ])
        logger.info('Generated data: {}'.format(data))
        query_str = urlencode(data)
        logger.info('Generated str: {}'.format(query_str))
        self.record_processor_response({
            'orderRefNum': order_id,
            'amount': amount,
            'customerName': user_name
        }, transaction_id=order_id, basket=basket)
        logger.info("Successfully created XStack payment url [%s] for basket [%d].", order_id, basket.id)
        data['payment_page_url'] = '{}?{}'.format(reverse('xstack:xstack_payment_intent'), query_str)
        return {'payment_page_url': data['payment_page_url']}

    def handle_processor_response(self, response, basket=None):
        """
        Record a successful XStack payment.

        Arguments:
            response (dict): Dictionary of parameters returned by XStack in the `postBackURL` query string.

        Keyword Arguments:
            basket (Basket): Basket being purchased via the payment processor.

        Raises:
            GatewayError: Indicates a general error or unexpected behavior on the part of XStack which prevented
                an approved payment from being executed.

        Returns:
            HandledProcessorResponse
        """
        order_id = response.get('orderRefNum')
        logger.info('\n\n\n{}\n\n\n'.format(response))

        response_statuses = {
            '500': 'Transaction Fail',
        }

        try:
            payment_status = response['status']
        except KeyError:
            msg = 'Response did not contain "status": {}'.format(response)
            self.record_processor_response({'error_msg': msg}, transaction_id=order_id, basket=basket)
            raise GatewayError()

        if payment_status != 200:
            msg = 'Payment unsuccessful due to {}:{}'.format(
                payment_status,
                response_statuses.get(payment_status, 'Status Code not found in expected responses')
            )
            self.record_processor_response({'error_msg': msg}, transaction_id=order_id, basket=basket)
            raise GatewayError(msg)
        self.record_processor_response(response, transaction_id=order_id, basket=basket)
        logger.info("Successfully recorded XStack payment [%s] for basket [%d].", order_id, basket.id)

        currency = basket.currency
        total = basket.total_incl_tax

        return HandledProcessorResponse(
            transaction_id=order_id,
            total=total,
            currency=currency,
            card_number='XStack Account',
            card_type=None
        )

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        """
        Perform refund.

        Since we do not have a refund policy yet we are leaving this function blank.
        """
        # TODO: Add refund logic here
        pass
