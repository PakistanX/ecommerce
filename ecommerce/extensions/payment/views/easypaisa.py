from rest_framework.views import APIView
from rest_framework import authentication
from rest_framework.response import Response
from rest_framework import status


class LoginToEasyPaisaView(APIView):
    authentication_classes = [authentication.SessionAuthentication]

    def get(self, request, **kwargs):
        return Response("<h3>Login</h3>", status=status.HTTP_200_OK)
