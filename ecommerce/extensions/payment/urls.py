from __future__ import absolute_import

from django.conf.urls import include, url

from ecommerce.extensions.payment.views import (
    PaymentFailedView, SDNFailure, cybersource, easypaisa, paypal, stripe, postex, xstack
)

CYBERSOURCE_APPLE_PAY_URLS = [
    url(r'^authorize/$', cybersource.CybersourceApplePayAuthorizationView.as_view(), name='authorize'),
    url(r'^start-session/$', cybersource.ApplePayStartSessionView.as_view(), name='start_session'),
]
CYBERSOURCE_URLS = [
    url(r'^apple-pay/', include((CYBERSOURCE_APPLE_PAY_URLS, 'apple_pay'))),
    url(r'^redirect/$', cybersource.CybersourceInterstitialView.as_view(), name='redirect'),
    url(r'^submit/$', cybersource.CybersourceSubmitView.as_view(), name='submit'),
    url(r'^api-submit/$', cybersource.CybersourceSubmitAPIView.as_view(), name='api_submit'),
]

PAYPAL_URLS = [
    url(r'^execute/$', paypal.PaypalPaymentExecutionView.as_view(), name='execute'),
    url(r'^profiles/$', paypal.PaypalProfileAdminView.as_view(), name='profiles'),
]

EASYPAISA_URLS = [
    url(r'^postback/$', easypaisa.EasyPaisaPostBackView.as_view(), name='postback'),
]

POSTEX_URLS = [
    url(r'^postback/$', postex.PostExPostBackAPI.as_view(), name='postback'),
    url(r'^redirect/$', postex.PostExPostBackView.as_view(), name='redirect'),
    url(r'^cod/$', postex.PostExCODPaymentView.as_view(), name='cod'),
]

XSTACK_URLS = [
    url(r'^postback/$', xstack.XStackPostBackView.as_view(), name='xstack_payment_intent'),
    url(r'^order$', xstack.XStackOrderCompletionView.as_view(), name='xstack_order_completion'),
]

SDN_URLS = [
    url(r'^failure/$', SDNFailure.as_view(), name='failure'),
]

STRIPE_URLS = [
    url(r'^submit/$', stripe.StripeSubmitView.as_view(), name='submit'),
]

urlpatterns = [
    url(r'^cybersource/', include((CYBERSOURCE_URLS, 'cybersource'))),
    url(r'^error/$', PaymentFailedView.as_view(), name='payment_error'),
    url(r'^paypal/', include((PAYPAL_URLS, 'paypal'))),
    url(r'^sdn/', include((SDN_URLS, 'sdn'))),
    url(r'^stripe/', include((STRIPE_URLS, 'stripe'))),
    url(r'^easypaisa/', include((EASYPAISA_URLS, 'easypaisa'))),
    url(r'^postex/', include((POSTEX_URLS, 'postex'))),
    url(r'^xstack/', include((XSTACK_URLS, 'xstack'))),
]
