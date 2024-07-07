""" PostEx payment processing. """
from __future__ import absolute_import, unicode_literals

import logging

from django.urls import reverse
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
        logger.info("Successfully created XStack payment url [%s] for basket [%d].", basket.order_number, basket.id)
        return {'payment_page_url': '{}'.format(reverse('xstack:xstack_payment_intent'))}

    def handle_processor_response(self, response, basket=None):
        """
        Record a successful XStack payment.

        Arguments:
            response (dict): Dictionary of parameters returned by XStack in the `postBackURL` query string.

        Keyword Arguments:
            basket (Basket): Basket being purchased via the payment processor.

        Raises:
            Exception: Indicates a general error or unexpected behavior on the part of XStack which prevented
                an approved payment from being executed.

        Returns:
            HandledProcessorResponse
        """
        logger.info('\n\n\n{}\n\n\n'.format(response))

        try:
            payment_status = response['payment_intent_response']['data']['last_payment_response']['status']
            if payment_status != 'PAYMENT_CAPTURED':
                msg = 'Payment unsuccessful for payment ID {}'.format(
                    response['payment_intent_response']['data']['_id'],
                )
                self.record_processor_response(
                    response,
                    transaction_id='Payment unsuccessful for payment ID {}, basket order no {}'.format(response['payment_intent_response']['data']['_id'], basket.order_number),
                    basket=basket,
                )
                raise Exception(msg)
        except KeyError:
            msg = 'Response did not contain payment_status: {}'.format(response)
            self.record_processor_response({'error_msg': msg}, transaction_id=basket.order_number, basket=basket)
            raise Exception()

        self.record_processor_response(
            response,
            transaction_id='XStack payment completion for {}'.format(basket.order_number),
            basket=basket,
        )
        logger.info("Successfully recorded XStack payment [%s] for basket [%d].", basket.order_number, basket.id)

        return HandledProcessorResponse(
            transaction_id=basket.order_number,
            total=basket.total_incl_tax,
            currency=basket.currency,
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
