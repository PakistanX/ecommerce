""" EasyPaisa payment processing. """
from __future__ import absolute_import, unicode_literals

import logging
from base64 import b64encode
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urlencode

from Crypto.Cipher import AES
from django.conf import settings
from django.urls import reverse
from six.moves.urllib.parse import urljoin

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse

logger = logging.getLogger(__name__)


class AESCipher(object):
    """Hashing class for EasyPaisa API."""

    def __init__(self, key):
        """Initialize key attributes."""
        self.block_size = AES.block_size
        self.key = bytes(key, 'utf-8')

    def encrypt(self, plain_text):
        """Encrypt string using AES."""
        plain_text = self.__pad(plain_text)
        # iv = Random.new().read(self.block_size)
        cipher = AES.new(self.key, AES.MODE_ECB)
        encrypted_text = cipher.encrypt(bytes(plain_text, 'utf-8'))
        return b64encode(encrypted_text).decode("utf-8")

    def __pad(self, plain_text):
        """Apply padding to string for hashing."""
        number_of_bytes_to_pad = self.block_size - len(plain_text) % self.block_size
        ascii_string = chr(number_of_bytes_to_pad)
        padding_str = number_of_bytes_to_pad * ascii_string
        padded_plain_text = plain_text + padding_str
        return padded_plain_text


class EasyPaisa(BasePaymentProcessor):
    """EasyPaisa API implementation."""

    NAME = 'easypaisa'

    # DEFAULT_PROFILE_NAME = 'default'

    def __init__(self, site):
        """
        Constructs a new instance of the EasyPaisa payment processor.

        Raises:
            KeyError: If a required setting is not configured for this payment processor
        """
        super(EasyPaisa, self).__init__(site)

    @property
    def cancel_url(self):
        return get_ecommerce_url(self.configuration['cancel_checkout_path'])

    @property
    def error_url(self):
        return get_ecommerce_url(self.configuration['error_path'])

    def get_courseid_title(self, line):
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
        """Create ordered dict from dict."""
        ordered_data = OrderedDict()
        for key, value in sorted(data.items()):
            ordered_data[key] = value
        return ordered_data

    def get_transaction_parameters(self, basket, request=None, use_client_side_checkout=False, **kwargs):
        """
        Create a new EasyPaisa payment.

        Arguments:
            basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which is used to construct PayPal's `return_url`.
            use_client_side_checkout (bool, optional): This value is not used.
            **kwargs: Additional parameters; not used by this method.

        Returns:
            dict: EasyPaisa-specific parameters required to complete a transaction. Must contain a URL
                to which users can be directed in order to approve a newly created payment.

        Raises:
            GatewayError: Indicates a general error or unexpected behavior on the part of PayPal which prevented
                a payment from being created.
        """
        logger.info('Starting easypaisa payment')
        logger.info(settings.PAYMENT_PROCESSOR_CONFIG)
        partner_code = basket.site.siteconfiguration.partner.short_code
        easy_paisa_config = settings.PAYMENT_PROCESSOR_CONFIG[partner_code.lower()][self.NAME]
        my_date = datetime.now() + timedelta(hours=5)
        aes = AESCipher(easy_paisa_config['hash_key'])
        store_id = easy_paisa_config['store_id']
        order_id = basket.order_number
        payment_method = easy_paisa_config['payment_method']
        amount = basket.total_incl_tax
        api_url = easy_paisa_config['api_url']
        return_url = urljoin(get_ecommerce_url(), reverse('easypaisa:postback'))
        data = self.create_ordered_dict({
            'amount': 1,
            'orderRefNum': order_id,
            'paymentMethod': payment_method,
            'storeId': store_id,
            'timeStamp': '',
        })
        query_str = urlencode(data)
        query_str = '{}{}'.format(query_str, my_date.strftime("%Y-%m-%dT%H:%M:%S"))
        logger.info('Generated str: {}'.format(query_str))
        hashed = aes.encrypt(query_str)
        str_param = self.create_ordered_dict({
            'storeId': store_id,
            'orderId': order_id,
            'transactionAmount': 1,
            'mobileAccountNo': '',
            'emailAddress': '',
            'transactionType': payment_method,
            'tokenExpiry': '',
            'bankIdentificationNumber': '',
            'encryptedHashRequest': hashed,
            'merchantPaymentMethod': '',
            'postBackURL': '',
            'signature': '',
        })
        return {
            'payment_page_url': '{}?{}'.format(api_url, urlencode(str_param))
        }

    def handle_processor_response(self, response, basket=None):
        """
        Record a successful EasyPaisa payment.

        Arguments:
            response (dict): Dictionary of parameters returned by EasyPaisa in the `postBackURL` query string.

        Keyword Arguments:
            basket (Basket): Basket being purchased via the payment processor.

        Returns:
            HandledProcessorResponse
        """
        order_id = response.get('orderRefNumber')
        logger.info('\n\n\n{}\n\n\n'.format(response))

        # TODO: Raise Gateway error on failure.

        self.record_processor_response(response, transaction_id=order_id, basket=basket)
        logger.info("Successfully recorded EasyPaisa payment [%s] for basket [%d].", order_id, basket.id)

        currency = basket.currency
        total = basket.total_incl_tax

        return HandledProcessorResponse(
            transaction_id=order_id,
            total=total,
            currency=currency,
            card_number='EasyPaisa Account',
            card_type=None
        )

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        """
        Perform refund.

        Since we do not have a refund policy yet we are leaving this function blank.
        """
        # TODO: Add refund logic here
        pass
