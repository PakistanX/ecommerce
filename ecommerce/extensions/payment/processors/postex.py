""" PostEx payment processing. """
from __future__ import absolute_import, unicode_literals

import logging
from collections import OrderedDict
from urllib.parse import urlencode

from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from six.moves.urllib.parse import urljoin

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse

logger = logging.getLogger(__name__)


class PostEx(BasePaymentProcessor):
    """PostEx API implementation."""

    NAME = 'postex'

    def __init__(self, site):
        """
        Constructs a new instance of the PostEx payment processor.

        Raises:
            KeyError: If a required setting is not configured for this payment processor
        """
        super(PostEx, self).__init__(site)

    @property
    def cancel_url(self):
        return get_ecommerce_url(self.configuration['cancel_checkout_path'])

    @property
    def error_url(self):
        return get_ecommerce_url(self.configuration['error_url'])

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
        Create a new PostEx payment.

        Arguments:
            basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which is used to construct PayPal's `return_url`.
            use_client_side_checkout (bool, optional): This value is not used.
            **kwargs: Additional parameters; not used by this method.

        Returns:
            dict: PostEx-specific parameters required to complete a transaction. Must contain a URL
                to which users can be directed in order to approve a newly created payment.
        """
        logger.info('Starting postex payment')
        merchant_code = self.configuration['merchant_code']
        api_url = self.configuration['url']
        api_key = self.configuration['key']
        order_id = basket.order_number
        amount = basket.total_incl_tax
        user_name = basket.owner.username
        return_url = urljoin(get_ecommerce_url(), reverse('postex:postback'))
        data = self.create_ordered_dict([
            ('customerName', user_name),
            ('amount', amount),
            ('apiKey', api_key),
            ('orderRefNum', order_id),
            ('merchantCode', merchant_code),
            ('customerPhoneNum', ''),
            ('customerAddress', ''),
        ])
        logger.info('Generated data: {}'.format(data))
        query_str = urlencode(data)
        logger.info('Generated str: {}'.format(query_str))
        self.record_processor_response({
            'orderRefNum': order_id,
            'amount': amount,
            'customerName': user_name
        }, transaction_id=order_id, basket=basket)
        logger.info("Successfully created PostEx payment [%s] for basket [%d].", order_id, basket.id)
        data['payment_page_url'] = '{}{}'.format(api_url, query_str)
        return {'payment_page_url': data['payment_page_url']}

    def handle_processor_response(self, response, basket=None):
        """
        Record a successful PostEx payment.

        Arguments:
            response (dict): Dictionary of parameters returned by PostEx in the `postBackURL` query string.

        Keyword Arguments:
            basket (Basket): Basket being purchased via the payment processor.

        Raises:
            GatewayError: Indicates a general error or unexpected behavior on the part of PostEx which prevented
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

        if payment_status != '200':
            msg = 'Payment unsuccessful due to {}:{}'.format(
                payment_status,
                response_statuses.get(payment_status, 'Status Code not found in expected responses')
            )
            self.record_processor_response({'error_msg': msg}, transaction_id=order_id, basket=basket)
            raise GatewayError(msg)

        self.record_processor_response(response, transaction_id=order_id, basket=basket)
        logger.info("Successfully recorded PostEx payment [%s] for basket [%d].", order_id, basket.id)

        currency = basket.currency
        total = basket.total_incl_tax

        return HandledProcessorResponse(
            transaction_id=order_id,
            total=total,
            currency=currency,
            card_number='PostEx Account',
            card_type=None
        )

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        """
        Perform refund.

        Since we do not have a refund policy yet we are leaving this function blank.
        """
        # TODO: Add refund logic here
        pass
