import logging
from rest_framework.views import APIView
from rest_framework import authentication
from rest_framework.response import Response
from rest_framework import status


logger = logging.getLogger(__name__)


class PostBackView(APIView):
    """Handle response from EasyPaisa API."""

    authentication_classes = [authentication.SessionAuthentication]

    def post(self, request):
        logger.info('\n\n\n{}\n\n\n'.format(request.POST))
