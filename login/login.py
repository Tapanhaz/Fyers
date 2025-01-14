import toml
from pyotp import TOTP
from fyers_apiv3 import fyersModel
import base64
import httpx
from urllib.parse import parse_qs, urlparse
import os
from datetime import datetime


class FyersLogin:
    def __init__(self, credentials_file="credentials.toml", token_file="access_token.txt"):
        with open(credentials_file, 'r') as f:
            config = toml.load(f)
        self.user_id = config['FYERS']['USER_ID']
        self.pin = config['FYERS']['PIN']
        self.client_id = config['FYERS']['APP_ID']
        self.secret_key = config['FYERS']['SECRET_KEY']
        self.redirect_uri = "https://127.0.0.1"
        self.response_type = "code"
        self.grant_type = "authorization_code"
        self.state = "sample"
        self.otp = TOTP(config['FYERS']['QR_CODE_TEXT']).now()
        self.base_urls = {
            "LOGIN_OTP": "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
            "VERIFY_OTP": "https://api-t2.fyers.in/vagator/v2/verify_otp",
            "VERIFY_PIN": "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
            "TOKEN": "https://api-t1.fyers.in/api/v3/token",
        }
        self.session = httpx.AsyncClient()
        self.token_file = token_file
    
    @staticmethod
    def get_encoded_string(string):
        string = str(string)
        base64_bytes = base64.b64encode(string.encode("ascii"))
        return base64_bytes.decode("ascii")
    
    async def send_login_otp(self):
        res = await self.session.post(url=self.base_urls["LOGIN_OTP"], 
                                      json={"fy_id": self.get_encoded_string(self.user_id), "app_id": "2"})
        return res.json()
    
    async def verify_otp(self, request_key):
        res = await self.session.post(url=self.base_urls["VERIFY_OTP"], 
                                      json={"request_key": request_key, "otp": self.otp})
        return res.json()
    
    async def verify_pin(self, request_key):
        payload = {
            "request_key": request_key,
            "identity_type": "pin",
            "identifier": self.get_encoded_string(self.pin)
        }
        res = await self.session.post(url=self.base_urls["VERIFY_PIN"], json=payload)
        self.session.headers.update({'authorization': f"Bearer {res.json()['data']['access_token']}"})
        return res.json()
    
    async def fetch_auth_token(self):
        payload = {
            "fyers_id": self.user_id,
            "app_id": self.client_id[:-4],
            "redirect_uri": self.redirect_uri,
            "appType": "100",
            "code_challenge": "",
            "state": "None",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True
        }
        res = await self.session.post(url=self.base_urls["TOKEN"], json=payload)
        url = res.json()['Url']
        parsed = urlparse(url)
        return parse_qs(parsed.query)['auth_code'][0]
    
    async def generate_token(self, auth_code):
        session = fyersModel.SessionModel(
            client_id=self.client_id,
            secret_key=self.secret_key,
            redirect_uri=self.redirect_uri,
            response_type=self.response_type,
            grant_type=self.grant_type
        )
        session.set_token(auth_code)
        response = session.generate_token()
        access_token = response['access_token']
        with open(self.token_file, 'w') as f:
            f.write(access_token)
        return access_token
    
    async def auto_login(self):
        send_otp_res = await self.send_login_otp()
        verify_otp_res = await self.verify_otp(send_otp_res["request_key"])
        verify_pin_res = await self.verify_pin(verify_otp_res["request_key"])
        auth_code = await self.fetch_auth_token()
        return await self.generate_token(auth_code)

    def is_token_from_today(self):
        if not os.path.exists(self.token_file):
            return False
        token_mod_time = os.path.getmtime(self.token_file)
        token_date = datetime.fromtimestamp(token_mod_time).date()
        return token_date == datetime.now().date()

    async def get_valid_token(self):
        if self.is_token_from_today():
            with open(self.token_file, 'r') as f:
                return f.read()
        return await self.auto_login()


class BrokerHandler:
    def __init__(self, credentials_file, access_token, log_path="../logs"):
        with open(credentials_file, 'r') as f:
            self.config = toml.load(f)
        self.client_id = self.config['FYERS']['APP_ID']
        self.bh = FyersLogin(credentials_file=credentials_file, token_file=access_token)
        self.log_path = log_path
        self.valid_token = None
        self.fyers_instance = None

    async def _initialize_fyers_instance(self):
        self.valid_token = await self.bh.get_valid_token()
        self.fyers_instance = fyersModel.FyersModel(client_id=self.client_id,
                                                    is_async=True, token=self.valid_token,
                                                    log_path=self.log_path)

    async def get_instance(self):
        if self.fyers_instance is None:
            await self._initialize_fyers_instance()
        return self.fyers_instance
