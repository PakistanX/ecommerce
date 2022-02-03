from rest_framework.views import APIView
from rest_framework import authentication
from rest_framework.response import Response
from rest_framework import status


class LoginToEasyPaisaView(APIView):
    authentication_classes = [authentication.SessionAuthentication]

    def get(self, request, **kwargs):

        # Check if token exists for this user
        # Call to /token to get token
        # Call to /login to get login page

        login_html = """
            <div>
                <div class="form-group col-md-6">
                    <label for="easypaisa-number" class="control-label">Number</label>
                    <input id="easypaisa-number" type="text" class="form-control" maxlength="11" required pattern="[0-9]*"/>
                </div>
                <div class="form-group col-md-6">
                    <label for="easypaisa-pwd" class="control-label">PIN</label>
                    <input id="easypaisa-pwd" type="password" class="form-control" maxlength="11" required pattern="[0-9]*"/>
                </div>
                <div class="payment-button col-sm-6 col-sm-offset-6 col-xs-12">
                    <button id="easypaisa-sbtn" type="submit" class="btn btn-primary btn-large col-sm-12 col-xs-12">Login</button>
                </div>
            </div>
        """
        return Response(login_html, status=status.HTTP_200_OK)

    def post(self, request):

        # Get json data after login from frontend
        # Save in database

        pass
