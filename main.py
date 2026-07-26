import os
import sys
import json
import uuid
import re
import base64
import time
import logging
import random
import string
import threading
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse
from concurrent.futures import ProcessPoolExecutor, as_completed

from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from flask_cors import CORS
import requests
import PyPDF2

# ============== LOGGING SETUP ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== APP & CONSTANTS SETUP ==============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, template_folder=BASE_DIR)
CORS(app)

DATA_FILE = os.path.join(BASE_DIR, "users.json")
TEMP_DIR = os.path.join(BASE_DIR, "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

# Telegram & System Constants
TELEGRAM_BOT_TOKEN = "8665531163:AAHBZIdUvBehN9jMBvKG3XrsMBHvMZCQl2I"
CHANNEL_USERNAME = "@UR_IMAGE"
CHANNEL_LINK = "https://t.me/UR_IMAGE"
OWNER_USERNAME = "@T_p0907"
OWNER_ID = 7759665144
BOT_NAME = "Aadhar Bot PDF"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━"
SESSION_TIMEOUT = 60

PLANS = {
    '10':  {'credits': 20,  'price': '₹49',  'lifetime': False},
    '20':  {'credits': 40,  'price': '₹100',  'lifetime': False},
    '50':  {'credits': 10,  'price': '₹250',  'lifetime': False},
    '100': {'credits': float('inf'), 'price': '₹1599', 'lifetime': True},
}

PROXY_CONFIG = {
    'use_proxy': False,
    'http': None,
    'https': None
}

# ============== DATABASE MANAGEMENT (users.json) ==============
_data_lock = threading.Lock()

def load_users():
    with _data_lock:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading users database: {e}")
        return {}

def save_users(data):
    with _data_lock:
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving user database: {e}")

def get_or_create_user(user_id="default_user", referrer=None):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            'credits': 1,
            'lifetime': False,
            'referred_by': str(referrer) if referrer else None,
            'referral_count': 0,
            'joined': datetime.now().isoformat()
        }
        if referrer:
            rid = str(referrer)
            if rid in users and rid != uid:
                users[rid]['credits'] = users[rid].get('credits', 0) + 1
                users[rid]['referral_count'] = users[rid].get('referral_count', 0) + 1
        save_users(users)
    return users[uid]

def ensure_user(user_id, referrer_id=None):
    uid = str(user_id)
    users = load_users()
    if uid not in users:
        users[uid] = {
            'credits': 1,
            'lifetime': False,
            'referred_by': str(referrer_id) if referrer_id else None,
            'referral_count': 0,
            'joined': datetime.now().isoformat()
        }
        if referrer_id:
            rid = str(referrer_id)
            if rid in users and rid != uid:
                users[rid]['credits'] = users[rid].get('credits', 0) + 1
                users[rid]['referral_count'] = users[rid].get('referral_count', 0) + 1
        save_users(users)
        return True
    return False

def get_user(user_id):
    users = load_users()
    return users.get(str(user_id))

def get_credits(user_id):
    u = get_user(user_id)
    if u is None:
        return 0
    if u.get('lifetime'):
        return float('inf')
    return u.get('credits', 0)

def is_lifetime(user_id):
    u = get_user(user_id)
    return u.get('lifetime', False) if u else False

def has_credits(user_id):
    return get_credits(user_id) > 0

def add_credits(user_id, amount, make_lifetime=False):
    uid = str(user_id)
    users = load_users()
    if uid not in users:
        users[uid] = {
            'credits': 0,
            'lifetime': False,
            'referred_by': None,
            'referral_count': 0,
            'joined': datetime.now().isoformat()
        }
    if make_lifetime:
        users[uid]['lifetime'] = True
    else:
        users[uid]['credits'] = users[uid].get('credits', 0) + amount
    save_users(users)

def deduct_user_credit(user_id="default_user"):
    uid = str(user_id)
    users = load_users()
    if uid in users and not users[uid].get('lifetime'):
        users[uid]['credits'] = max(0, users[uid].get('credits', 0) - 1)
        save_users(users)

def all_users():
    return load_users()

# ============== PROXY CONFIG & SETUP ==============
PROXY_CONFIG = {
    'use_proxy': False,
    'http': None,
    'https': None
}

def setup_proxy():
    proxy_url = os.environ.get('PROXY_URL', '').strip()
    if proxy_url:
        try:
            parsed = urlparse(proxy_url)
            if parsed.scheme in ['http', 'https', 'socks5', 'socks5h']:
                PROXY_CONFIG['use_proxy'] = True
                PROXY_CONFIG['http'] = proxy_url
                PROXY_CONFIG['https'] = proxy_url
                logger.info(f"Proxy initialized: {proxy_url}")
            else:
                logger.warning(f"Invalid PROXY_URL scheme '{parsed.scheme}'. Supported schemes: http, https, socks5, socks5h")
        except Exception as e:
            logger.error(f"Invalid PROXY_URL: {e}")
    else:
        PROXY_CONFIG['use_proxy'] = False
        logger.info("No PROXY_URL set. Direct connection will be used (Note: UIDAI blocks foreign cloud IPs like Railway).")

setup_proxy()

def create_session(use_proxy=None):
    session = requests.Session()
    session.mount('https://', requests.adapters.HTTPAdapter(
        pool_connections=10, pool_maxsize=10, max_retries=3, pool_block=False
    ))
    if use_proxy is None:
        use_proxy = PROXY_CONFIG['use_proxy']
    if use_proxy and PROXY_CONFIG['http']:
        session.proxies = {
            'http': PROXY_CONFIG['http'],
            'https': PROXY_CONFIG['https']
        }
        logger.info(f"Session created using proxy: {PROXY_CONFIG['http']}")
    return session

uidai_session = None
def get_uidai_session():
    global uidai_session
    if uidai_session is None:
        uidai_session = create_session()
    elif PROXY_CONFIG['use_proxy'] and PROXY_CONFIG['http']:
        uidai_session.proxies = {
            'http': PROXY_CONFIG['http'],
            'https': PROXY_CONFIG['https']
        }
    return uidai_session

telegram_session = None
def get_telegram_session():
    global telegram_session
    if telegram_session is None:
        telegram_session = create_session()
    elif PROXY_CONFIG['use_proxy'] and PROXY_CONFIG['http']:
        telegram_session.proxies = {
            'http': PROXY_CONFIG['http'],
            'https': PROXY_CONFIG['https']
        }
    return telegram_session

# ============== TELEGRAM & AUTH HELPERS ==============
def is_channel_member(user_id):
    if str(user_id) == "default_user":
        return True
    try:
        val = int(user_id)
        if val == OWNER_ID:
            return True
    except ValueError:
        return True

    try:
        r = get_telegram_session().get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember",
            params={'chat_id': CHANNEL_USERNAME, 'user_id': user_id},
            timeout=5
        ).json()
        if r.get('ok'):
            status = r['result']['status']
            return status in ('member', 'administrator', 'creator')
    except Exception as e:
        logger.error(f"Channel check error: {e}")
    return False

def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    try:
        response = get_telegram_session().post(url, json=data, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Error sending telegram message: {e}")
        return None

def enforce_channel_membership(user_id):
    if str(user_id) == "default_user":
        return True
    
    if not is_channel_member(user_id):
        users = load_users()
        uid = str(user_id)
        if uid in users:
            credits_to_clear = users[uid].get('credits', 0)
            lifetime = users[uid].get('lifetime', False)
            if credits_to_clear > 0 or lifetime:
                users[uid]['credits'] = 0
                users[uid]['lifetime'] = False
                save_users(users)
                
                msg = (
                    f"<b>⚠️ Account Alert</b>\n"
                    f"{DIVIDER}\n"
                    f"आपने हमारा Telegram Channel left कर दिया है, इसलिए आपका account balance 0 कर दिया गया है।\n\n"
                    f"अपना balance वापस लेने के लिए कृपया Admin ({OWNER_USERNAME}) से संपर्क करें।\n"
                    f"{DIVIDER}"
                )
                send_telegram_message(user_id, msg)
                logger.info(f"User {user_id} left channel. Credits zeroed.")
        return False
    return True

def authenticate_user(user_id, password):
    if str(user_id) == "default_user":
        return True, None
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        return False, "User account not found. Register via Telegram Bot."
    user_data = users[uid]
    if user_data.get('password') != password:
        return False, "Invalid password."
    return True, user_data

def authenticate_admin(admin_id, password):
    if str(admin_id) != str(OWNER_ID):
        return False, "Unauthorized: Admin access only."
    return authenticate_user(admin_id, password)

def answer_callback_query(callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    data = {'callback_query_id': callback_query_id}
    if text:
        data['text'] = text
    try:
        get_telegram_session().post(url, json=data, timeout=5)
    except Exception as e:
        logger.error(f"Error answering callback: {e}")

def send_photo(chat_id, photo_bytes, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    files = {'photo': ('captcha.png', photo_bytes, 'image/png')}
    data = {'chat_id': chat_id, 'parse_mode': 'HTML'}
    if caption:
        data['caption'] = caption
    try:
        response = get_telegram_session().post(url, data=data, files=files, timeout=20)
        return response.json()
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        return None

def send_document(chat_id, file_path, caption=None, filename="Aadhaar.pdf"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            files = {'document': (filename, f, 'application/pdf')}
            data = {'chat_id': chat_id, 'parse_mode': 'HTML'}
            if caption:
                data['caption'] = caption
            response = get_telegram_session().post(url, data=data, files=files, timeout=30).json()
        try:
            os.remove(file_path)
        except Exception:
            pass
        return response
    except Exception as e:
        logger.error(f"Error sending document: {e}")
        return None

# ============== PDF PASSWORD CRACKER ==============
class PDFPasswordCracker:
    def __init__(self):
        self.found_password = None
        self.stop_flag = False

    @staticmethod
    def _try_password(pdf_bytes, password):
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
            if pdf_reader.decrypt(password):
                return True, password
            return False, None
        except Exception:
            return False, None

    def decrypt_pdf(self, pdf_bytes, password):
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
            pdf_reader.decrypt(password)
            pdf_writer = PyPDF2.PdfWriter()
            for page in pdf_reader.pages:
                pdf_writer.add_page(page)
            
            output = BytesIO()
            pdf_writer.write(output)
            output.seek(0)
            return output.getvalue()
        except Exception as e:
            logger.error(f"Error decrypting PDF: {e}")
            return None

    def crack_pdf_bytes(self, pdf_bytes, name):
        self.found_password = None
        self.stop_flag = False

        name_upper = (name or "MR").upper()
        patterns = []
        name_prefix = name_upper[:4] if len(name_upper) >= 4 else name_upper
        patterns.append(('first4', name_prefix))
        if len(name_upper) >= 6:
            patterns.append(('first6', name_upper[:6]))
        name_full = name_upper[:10] if len(name_upper) > 10 else name_upper
        patterns.append(('full', name_full))
        patterns.append(('lower_first4', name_prefix.lower()))
        if len(name_upper) >= 6:
            patterns.append(('lower_first6', name_upper[:6].lower()))
        patterns.append(('title_first4', name_prefix.title()))
        patterns.append(('first4_short', name_prefix[:4]))
        patterns.append(('with_at', f"{name_prefix}@"))
        patterns.append(('with_hash', f"{name_prefix}#"))
        patterns.append(('with_exclaim', f"{name_prefix}!"))
        patterns.append(('year_first', "@"))
        patterns.append(('only_name', name_prefix))

        current_year = datetime.now().year
        common_years = list(range(current_year, 1929, -1))

        prioritized_passwords = []
        for year in common_years:
            for pattern_name, prefix in patterns:
                if pattern_name == 'year_first':
                    password = f"{year}{prefix}"
                elif pattern_name == 'only_name':
                    password = prefix
                elif pattern_name == 'first4_short':
                    password = f"{prefix[:4]}{year}"
                elif pattern_name == 'with_at':
                    password = f"{prefix}@{year}"
                elif pattern_name == 'with_hash':
                    password = f"{prefix}#{year}"
                elif pattern_name == 'with_exclaim':
                    password = f"{prefix}!{year}"
                else:
                    password = f"{prefix}{year}"
                prioritized_passwords.append(password)

        seen = set()
        unique_passwords = []
        for pwd in prioritized_passwords:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)

        max_workers = min(os.cpu_count() or 4, 8)
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            batch_size = 50
            futures = []
            total_passwords = len(unique_passwords)

            for i, pwd in enumerate(unique_passwords):
                if self.stop_flag:
                    break
                futures.append(executor.submit(self._try_password, pdf_bytes, pwd))
                if len(futures) >= batch_size or i == total_passwords - 1:
                    for future in as_completed(futures):
                        if self.stop_flag:
                            break
                        try:
                            success, found_pwd = future.result(timeout=2)
                            if success:
                                self.found_password = found_pwd
                                self.stop_flag = True
                                decrypted_bytes = self.decrypt_pdf(pdf_bytes, found_pwd)
                                return True, found_pwd, decrypted_bytes
                        except Exception:
                            continue
                    futures = []

        if not self.stop_flag:
            no_year_passwords = [prefix for pattern_name, prefix in patterns if pattern_name not in ['only_name']]
            for password in no_year_passwords:
                if self.stop_flag:
                    break
                success, found_pwd = self._try_password(pdf_bytes, password)
                if success:
                    self.found_password = found_pwd
                    self.stop_flag = True
                    decrypted_bytes = self.decrypt_pdf(pdf_bytes, found_pwd)
                    return True, found_pwd, decrypted_bytes

        return False, None, None

# ============== AADHAAR SERVICE CLASS ==============
class AadhaarService:
    def __init__(self):
        self.base_headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en_IN',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Origin': 'https://myaadhaar.uidai.gov.in',
            'Referer': 'https://myaadhaar.uidai.gov.in/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
            'appid': 'MYAADHAAR',
            'sec-ch-ua': '"Not-A.Brand";v="99", "Chromium";v="124"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
        }
        self.cracker = PDFPasswordCracker()

    @property
    def session(self):
        s = get_uidai_session()
        s.headers.update(self.base_headers)
        return s

    def generate_transaction_id(self):
        return str(uuid.uuid4())

    def is_base64(self, s):
        if not isinstance(s, str) or len(s) < 100:
            return False
        if s.startswith('data:'):
            s = s.split(',')[1] if ',' in s else s
        if len(s) % 4 != 0:
            return False
        try:
            base64.b64decode(s)
            return True
        except:
            return False

    def detect_and_decode_base64(self, data):
        decoded_items = []
        if isinstance(data, dict):
            for key, value in list(data.items()):
                if isinstance(value, str) and len(value) > 100 and self.is_base64(value):
                    try:
                        clean_base64 = value.split(',')[1] if value.startswith('data:') and ',' in value else value
                        decoded_bytes = base64.b64decode(clean_base64)
                        decoded_items.append({'field': key, 'data': decoded_bytes})
                    except Exception as e:
                        logger.error(f"Base64 decode error: {e}")
                if isinstance(value, (dict, list)):
                    decoded_items.extend(self.detect_and_decode_base64(value))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    decoded_items.extend(self.detect_and_decode_base64(item))
        return decoded_items

    def get_captcha(self):
        transaction_id = self.generate_transaction_id()
        sess = self.session
        sess.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        captcha_data = {'captchaLength': '6', 'captchaType': '2', 'audioCaptchaRequired': True}
        try:
            response = sess.post(
                'https://tathya.uidai.gov.in/audioCaptchaService/api/captcha/v3/generation',
                json=captcha_data, timeout=15
            )
            if response.status_code != 200:
                return None, None, None, f"HTTP {response.status_code}"
            resp_json = response.json()
            captcha_txn_id = resp_json.get('transactionId')
            captcha_base64 = resp_json.get('imageBase64')
            if not captcha_base64:
                for key, value in resp_json.items():
                    if isinstance(value, str) and len(value) > 100 and self.is_base64(value):
                        captcha_base64 = value
                        break
            if not captcha_base64:
                return None, None, None, "Captcha image missing in response"
            
            if captcha_base64.startswith('data:image'):
                clean_base64 = captcha_base64
            else:
                clean_base64 = f"data:image/png;base64,{captcha_base64}"
                
            return clean_base64, captcha_txn_id, transaction_id, None
        except requests.exceptions.Timeout:
            logger.error("UIDAI Captcha connection timed out.")
            return None, None, None, "UIDAI Server Connection Timed Out. (Note: Foreign datacenter IPs like Railway are blocked by UIDAI — Please set PROXY_URL env var in Railway)"
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"UIDAI Connection error: {ce}")
            return None, None, None, "UIDAI Connection Failed. Please set PROXY_URL env var in Railway with an Indian Proxy."
        except Exception as e:
            logger.error(f"Error getting captcha: {str(e)}")
            return None, None, None, str(e)

    def send_eid_otp(self, mobile, name, captcha_code, captcha_txn_id, transaction_id):
        sess = self.session
        sess.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        request_data = {
            'mobileNumber': mobile, 'dob': None, 'email': None,
            'name': name.upper(), 'option': 'EID', 'otp': None,
            'otpTxnId': None, 'captchaTxnId': captcha_txn_id,
            'captcha': captcha_code, 'resendOtp': False
        }
        try:
            response = sess.post(
                'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid',
                json=request_data, timeout=15
            )
            if response.status_code == 200:
                resp_json = response.json()
                if 'responseData' in resp_json:
                    response_data = resp_json['responseData']
                    otp_txn_id = response_data.get('otpTxnId')
                    status = response_data.get('status')
                    if otp_txn_id and status == "Success":
                        return True, otp_txn_id, "OTP sent successfully"
                    else:
                        return False, None, response_data.get('message', 'Captcha or mobile details invalid')
                else:
                    return False, None, 'Invalid UIDAI response format'
            else:
                return False, None, f'HTTP {response.status_code}'
        except requests.exceptions.Timeout:
            return False, None, "UIDAI Server Timed Out. Please set PROXY_URL env var in Railway."
        except requests.exceptions.ConnectionError:
            return False, None, "UIDAI Connection Failed. Please set PROXY_URL env var in Railway."
        except Exception as e:
            return False, None, str(e)

    def verify_eid_otp(self, mobile, name, otp_code, otp_txn_id, captcha_txn_id, captcha_code):
        sess = self.session
        sess.headers.update({'x-request-id': self.generate_transaction_id()})
        verify_data = {
            'mobileNumber': mobile, 'dob': None, 'name': name.upper(),
            'email': None, 'option': 'EID', 'otp': otp_code,
            'otpTxnId': otp_txn_id, 'captchaTxnId': captcha_txn_id,
            'captcha': captcha_code, 'resendOtp': False
        }
        try:
            response = sess.post(
                'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid',
                json=verify_data, timeout=15
            )
            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get('status') == 200 or resp_json.get('status') == "Success":
                    if 'responseData' in resp_json:
                        response_data = resp_json['responseData']
                        eid_number = response_data.get('eidNumber')
                        name_from_response = response_data.get('name', name)
                        if eid_number:
                            return True, eid_number, name_from_response, "Verification successful"
                        else:
                            return False, None, None, "No EID found for given details"
                    else:
                        return False, None, None, "Invalid response data from UIDAI"
                else:
                    error_msg = resp_json.get('errorDetails', {}).get('messageEnglish', 'OTP verification failed')
                    return False, None, None, error_msg
            else:
                return False, None, None, f'HTTP {response.status_code}'
        except requests.exceptions.Timeout:
            return False, None, None, "UIDAI Server Timed Out. Please set PROXY_URL env var in Railway."
        except requests.exceptions.ConnectionError:
            return False, None, None, "UIDAI Connection Failed. Please set PROXY_URL env var in Railway."
        except Exception as e:
            return False, None, None, str(e)

    def send_aadhaar_otp(self, eid_number, captcha_value, captcha_txn_id, transaction_id):
        sess = self.session
        sess.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        otp_request_data = {
            'eidNumber': eid_number, 'idType': 'eid',
            'captchaTxnId': captcha_txn_id, 'captchaValue': captcha_value,
            'transactionId': transaction_id, 'resendOTP': False
        }
        try:
            response = sess.post(
                'https://tathya.uidai.gov.in/unifiedAppAuthService/api/v2/generate/aadhaar/otp',
                json=otp_request_data, timeout=15
            )
            if response.status_code == 200:
                resp_json = response.json()
                otp_txn_id = resp_json.get('txnId')
                status = resp_json.get('status')
                message = resp_json.get('message', 'OTP Generation Failed')
                if otp_txn_id and status == "Success":
                    return True, otp_txn_id, message
                else:
                    return False, None, message
            else:
                return False, None, f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            return False, None, "UIDAI Server Timed Out. Please set PROXY_URL env var in Railway."
        except requests.exceptions.ConnectionError:
            return False, None, "UIDAI Connection Failed. Please set PROXY_URL env var in Railway."
        except Exception as e:
            return False, None, str(e)

    def download_aadhaar_pdf(self, eid_number, otp, otp_txn_id, transaction_id, mask=False):
        sess = self.session
        sess.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        download_data = {'eid': eid_number, 'mask': mask, 'otp': otp, 'otpTxnId': otp_txn_id}
        try:
            response = sess.post(
                'https://tathya.uidai.gov.in/downloadAadhaarService/api/aadhaar/download',
                json=download_data, timeout=20
            )
            if response.status_code == 200:
                resp_json = response.json()
                decoded_files = self.detect_and_decode_base64(resp_json)
                if decoded_files:
                    return True, decoded_files[0]['data'], None
                else:
                    error_msg = resp_json.get('message', resp_json.get('errorMessage', 'No PDF data found'))
                    return False, None, error_msg
            else:
                return False, None, f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            return False, None, "UIDAI Server Timed Out. Please set PROXY_URL env var in Railway."
        except requests.exceptions.ConnectionError:
            return False, None, "UIDAI Connection Failed. Please set PROXY_URL env var in Railway."
        except Exception as e:
            return False, None, str(e)

service = AadhaarService()

# ============== FLASK ROUTES ==============
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory(BASE_DIR, path)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    user_id = str(data.get('user_id', '')).strip()
    password = str(data.get('password', '')).strip()
    
    if not user_id or not password:
        return jsonify({'success': False, 'message': 'User ID and Password are required'}), 400
        
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    enforce_channel_membership(user_id)
    
    users = load_users()
    user_data = users.get(user_id, {})
    
    return jsonify({
        'success': True,
        'user_id': user_id,
        'credits': 'Unlimited (Lifetime)' if user_data.get('lifetime') else user_data.get('credits', 0),
        'lifetime': user_data.get('lifetime', False)
    })

@app.route('/api/user/status', methods=['GET'])
def user_status():
    user_id = request.args.get('user_id', 'default_user').strip()
    password = request.args.get('password', '').strip()
    referrer = request.args.get('ref', None)
    
    if user_id == "default_user":
        u = get_or_create_user(user_id, referrer)
        return jsonify({
            'user_id': user_id,
            'credits': 0,
            'lifetime': False,
            'referral_count': 0,
            'joined': u.get('joined', '')[:10]
        })
        
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    enforce_channel_membership(user_id)
    
    users = load_users()
    u = users.get(user_id, {})
    return jsonify({
        'user_id': user_id,
        'credits': 'Unlimited (Lifetime)' if u.get('lifetime') else u.get('credits', 0),
        'lifetime': u.get('lifetime', False),
        'referral_count': u.get('referral_count', 0),
        'joined': u.get('joined', '')[:10]
    })

@app.route('/api/captcha', methods=['POST'])
def fetch_captcha():
    captcha_b64, captcha_txn_id, transaction_id, err = service.get_captcha()
    if captcha_b64:
        return jsonify({
            'success': True,
            'captcha_image': captcha_b64,
            'captcha_txn_id': captcha_txn_id,
            'transaction_id': transaction_id
        })
    else:
        return jsonify({'success': False, 'message': err or 'Failed to generate captcha'}), 400

@app.route('/api/mobile/send-otp', methods=['POST'])
def mobile_send_otp():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    password = data.get('password', '').strip()
    
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    if not enforce_channel_membership(user_id):
        return jsonify({'success': False, 'message': 'Channel membership required. Balance has been set to 0.'}), 403

    users = load_users()
    u = users.get(user_id, {})
    if u.get('credits', 0) <= 0 and not u.get('lifetime', False):
        return jsonify({'success': False, 'message': 'Insufficient credits. Please refer or buy credits.'}), 403

    mobile = data.get('mobile', '').strip()
    name = data.get('name', 'MR').strip()
    captcha_code = data.get('captcha_code', '').strip()
    captcha_txn_id = data.get('captcha_txn_id', '')
    transaction_id = data.get('transaction_id', '')

    if not re.match(r'^\d{10}$', mobile):
        return jsonify({'success': False, 'message': 'Invalid 10-digit mobile number'}), 400

    success, otp_txn_id, msg = service.send_eid_otp(mobile, name, captcha_code, captcha_txn_id, transaction_id)
    if success:
        return jsonify({'success': True, 'otp_txn_id': otp_txn_id, 'message': msg})
    else:
        return jsonify({'success': False, 'message': msg}), 400

@app.route('/api/mobile/verify-otp', methods=['POST'])
def mobile_verify_otp():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    password = data.get('password', '').strip()
    
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    if not enforce_channel_membership(user_id):
        return jsonify({'success': False, 'message': 'Channel membership required. Balance has been set to 0.'}), 403

    mobile = data.get('mobile', '').strip()
    name = data.get('name', 'MR').strip()
    otp_code = data.get('otp', '').strip()
    otp_txn_id = data.get('otp_txn_id', '')
    captcha_txn_id = data.get('captcha_txn_id', '')
    captcha_code = data.get('captcha_code', '')

    if not re.match(r'^\d{6}$', otp_code):
        return jsonify({'success': False, 'message': 'OTP must be 6 digits'}), 400

    success, eid_number, name_from_resp, msg = service.verify_eid_otp(
        mobile, name, otp_code, otp_txn_id, captcha_txn_id, captcha_code
    )
    if success:
        return jsonify({
            'success': True,
            'eid_number': eid_number,
            'verified_name': name_from_resp or name,
            'message': msg
        })
    else:
        return jsonify({'success': False, 'message': msg}), 400

@app.route('/api/aadhaar/send-otp', methods=['POST'])
def aadhaar_send_otp():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    password = data.get('password', '').strip()
    
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    if not enforce_channel_membership(user_id):
        return jsonify({'success': False, 'message': 'Channel membership required. Balance has been set to 0.'}), 403

    users = load_users()
    u = users.get(user_id, {})
    if u.get('credits', 0) <= 0 and not u.get('lifetime', False):
        return jsonify({'success': False, 'message': 'Insufficient credits. Please refer or buy credits.'}), 403

    eid_number = data.get('eid', '').strip().replace(' ', '')
    captcha_code = data.get('captcha_code', '').strip()
    captcha_txn_id = data.get('captcha_txn_id', '')
    transaction_id = data.get('transaction_id', '')

    if len(eid_number) < 10:
        return jsonify({'success': False, 'message': 'Invalid Aadhaar / EID number'}), 400

    success, otp_txn_id, msg = service.send_aadhaar_otp(eid_number, captcha_code, captcha_txn_id, transaction_id)
    if success:
        return jsonify({'success': True, 'otp_txn_id': otp_txn_id, 'message': msg})
    else:
        return jsonify({'success': False, 'message': msg}), 400

@app.route('/api/aadhaar/download', methods=['POST'])
def aadhaar_download():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    password = data.get('password', '').strip()
    
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    if not enforce_channel_membership(user_id):
        return jsonify({'success': False, 'message': 'Channel membership required. Balance has been set to 0.'}), 403

    users = load_users()
    u = users.get(user_id, {})
    if u.get('credits', 0) <= 0 and not u.get('lifetime', False):
        return jsonify({'success': False, 'message': 'Insufficient credits. Please refer or buy credits.'}), 403

    eid_number = data.get('eid', '').strip().replace(' ', '')
    otp_code = data.get('otp', '').strip()
    otp_txn_id = data.get('otp_txn_id', '')
    transaction_id = data.get('transaction_id', '')
    verified_name = data.get('verified_name', 'Mr')

    if not re.match(r'^\d{6}$', otp_code):
        return jsonify({'success': False, 'message': 'OTP must be 6 digits'}), 400

    success, pdf_bytes, err = service.download_aadhaar_pdf(eid_number, otp_code, otp_txn_id, transaction_id)
    if not success or not pdf_bytes:
        return jsonify({'success': False, 'message': err or 'Failed to download e-Aadhaar PDF'}), 400

    crack_success, found_password, decrypted_bytes = service.cracker.crack_pdf_bytes(pdf_bytes, verified_name)
    deduct_user_credit(user_id)

    if crack_success and decrypted_bytes:
        b64_pdf = base64.b64encode(decrypted_bytes).decode('utf-8')
        return jsonify({
            'success': True,
            'unlocked': True,
            'password': found_password,
            'filename': f"Aadhaar_{verified_name}.pdf",
            'pdf_base64': f"data:application/pdf;base64,{b64_pdf}"
        })
    else:
        b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        return jsonify({
            'success': True,
            'unlocked': False,
            'message': 'PDF downloaded. Enter password: First 4 letters of Name + Birth Year (e.g. RAJE1995)',
            'filename': f"eAadhaar_{verified_name}.pdf",
            'pdf_base64': f"data:application/pdf;base64,{b64_pdf}"
        })

@app.route('/api/pdf/unlock-file', methods=['POST'])
def unlock_file():
    user_id = request.form.get('user_id', 'default_user').strip()
    password = request.form.get('password', '').strip()
    
    success, res = authenticate_user(user_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    if not enforce_channel_membership(user_id):
        return jsonify({'success': False, 'message': 'Channel membership required. Balance has been set to 0.'}), 403

    users = load_users()
    u = users.get(user_id, {})
    if u.get('credits', 0) <= 0 and not u.get('lifetime', False):
        return jsonify({'success': False, 'message': 'Insufficient credits. Please refer or buy credits.'}), 403

    if 'pdf' not in request.files:
        return jsonify({'success': False, 'message': 'No PDF file uploaded'}), 400

    file = request.files['pdf']
    name = request.form.get('name', 'MR').strip()

    pdf_bytes = file.read()
    if not pdf_bytes.startswith(b'%PDF'):
        return jsonify({'success': False, 'message': 'Uploaded file is not a valid PDF'}), 400

    crack_success, found_password, decrypted_bytes = service.cracker.crack_pdf_bytes(pdf_bytes, name)
    deduct_user_credit(user_id)

    if crack_success and decrypted_bytes:
        b64_pdf = base64.b64encode(decrypted_bytes).decode('utf-8')
        return jsonify({
            'success': True,
            'unlocked': True,
            'password': found_password,
            'filename': f"Unlocked_{file.filename}",
            'pdf_base64': f"data:application/pdf;base64,{b64_pdf}"
        })
    else:
        return jsonify({
            'success': False,
            'message': f"Could not unlock PDF for name '{name}'. Check name spelling or password pattern."
        }), 400

@app.route('/api/plans', methods=['GET'])
def get_plans():
    return jsonify({
        'plans': [
            {'id': '10', 'name': '10 Credits', 'credits': 20, 'price': '₹49', 'popular': False},
            {'id': '20', 'name': '20 Credits', 'credits': 40, 'price': '₹100', 'popular': True},
            {'id': '50', 'name': '50 Credits', 'credits': 10, 'price': '₹250', 'popular': False},
            {'id': '100', 'name': 'Lifetime Unlimited', 'credits': 'Unlimited', 'price': '₹1599', 'popular': False}
        ],
        'owner_telegram': OWNER_USERNAME
    })

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    admin_id = request.args.get('admin_id', '').strip()
    password = request.args.get('password', '').strip()
    
    success, res = authenticate_admin(admin_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    users = load_users()
    total_users = len(users)
    lifetime_count = sum(1 for u in users.values() if u.get('lifetime'))
    total_credits = sum(u.get('credits', 0) for u in users.values() if not u.get('lifetime'))
    return jsonify({
        'total_users': total_users,
        'lifetime_users': lifetime_count,
        'active_credits': total_credits,
        'users': users
    })

@app.route('/api/admin/add-credits', methods=['POST'])
def admin_add_credits():
    data = request.json or {}
    admin_id = data.get('admin_id', '').strip()
    password = data.get('password', '').strip()
    target_id = str(data.get('user_id', 'default_user')).strip()
    amount = data.get('amount', 10)
    
    success, res = authenticate_admin(admin_id, password)
    if not success:
        return jsonify({'success': False, 'message': res}), 401
        
    users = load_users()
    if target_id not in users:
        users[target_id] = {
            'credits': 0,
            'lifetime': False,
            'referred_by': None,
            'referral_count': 0,
            'joined': datetime.now().isoformat()
        }
    
    if amount == -1:
        users[target_id]['lifetime'] = True
    else:
        users[target_id]['credits'] = users[target_id].get('credits', 0) + amount
    
    save_users(users)
    
    gift_text = "Lifetime" if amount == -1 else f"{amount} credits"
    notify_msg = (
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"🎁 <b>Credits Received!</b>\n\n"
        f"Admin has granted you <b>{gift_text}</b>.\n"
        f"{DIVIDER}"
    )
    send_telegram_message(target_id, notify_msg)
    
    return jsonify({'success': True, 'message': f"Granted {amount} credits to {target_id}"})


# ============== TELEGRAM BOT SESSION & KEYBOARD HELPERS ==============
user_sessions = {}
_sessions_lock = threading.Lock()

def get_session(chat_id):
    with _sessions_lock:
        return user_sessions.get(chat_id, {'step': 'main', 'data': {}, 'last_activity': time.time()})

def set_session(chat_id, step, data=None):
    with _sessions_lock:
        existing = user_sessions.get(chat_id, {})
        d = data if data is not None else existing.get('data', {})
        user_sessions[chat_id] = {'step': step, 'data': d, 'last_activity': time.time()}

def clear_session(chat_id):
    with _sessions_lock:
        user_sessions[chat_id] = {'step': 'main', 'data': {}, 'last_activity': time.time()}

def _cleanup_sessions():
    while True:
        time.sleep(20)
        try:
            expired = []
            with _sessions_lock:
                for cid, s in list(user_sessions.items()):
                    if s.get('step', 'main') != 'main':
                        idle = time.time() - s.get('last_activity', time.time())
                        if idle > SESSION_TIMEOUT:
                            user_sessions[cid] = {'step': 'main', 'data': {}, 'last_activity': time.time()}
                            expired.append(cid)
            for cid in expired:
                try:
                    send_telegram_message(cid,
                        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                        f"<b>〔 Session Expired 〕</b>\n\n"
                        f"◈  Reason   ·  Idle for 60 seconds\n"
                        f"◈  Credits  ·  Not deducted\n\n"
                        f"{DIVIDER}\n"
                        f"<i>◌  Select a method below to start again.</i>",
                        reply_markup=get_main_keyboard()
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")

def get_main_keyboard():
    return {
        'keyboard': [
            ['🔑 Create Account', '👤 My Account']
        ],
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

def get_cancel_keyboard():
    return {'inline_keyboard': [[{'text': '✗  Cancel', 'callback_data': 'cancel'}]]}

def get_buy_keyboard():
    return {
        'inline_keyboard': [
            [{'text': '◆  10 Credits  —  ₹49',  'callback_data': 'buy_10'}],
            [{'text': '◆  20 Credits  —  ₹100',  'callback_data': 'buy_20'}],
            [{'text': '◆  50 Credits  —  ₹250',  'callback_data': 'buy_50'}],
            [{'text': '◆  Lifetime    —  ₹1599', 'callback_data': 'buy_100'}],
        ]
    }

def get_join_keyboard():
    return {
        'inline_keyboard': [
            [{'text': '◆  Join Channel',    'url': CHANNEL_LINK}],
            [{'text': '◇  I have joined ✓', 'callback_data': 'check_join'}],
        ]
    }

_bot_username = None
def get_bot_username():
    global _bot_username
    if _bot_username:
        return _bot_username
    try:
        r = get_telegram_session().get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=5
        ).json()
        if r.get('ok'):
            _bot_username = r['result']['username']
    except Exception:
        pass
    return _bot_username or "a_for_aadhar_bot"

def show_credits_info(chat_id):
    u = get_user(chat_id)
    cr = get_credits(chat_id)
    cr_display = "<b>Lifetime</b>" if cr == float('inf') else f"<b>{int(cr)}</b>"
    ref_count = u.get('referral_count', 0) if u else 0
    joined = u.get('joined', '')[:10] if u else '—'
    send_telegram_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>〔 My Credits 〕</b>\n\n"
        f"◈  Balance     ·  {cr_display}\n"
        f"◈  Referrals   ·  {ref_count}\n"
        f"◈  Member since·  {joined}\n\n"
        f"{DIVIDER}\n"
        f"<i>◌  1 credit = 1 Aadhaar download\n"
        f"◌  Earn free credits via your referral link</i>"
    )

def show_buy_menu(chat_id):
    send_telegram_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>〔 Buy Credits 〕</b>\n\n"
        f"◈  10 credits    ·  <b>₹49</b>\n"
        f"◈  20 credits    ·  <b>₹100</b>\n"
        f"◈  50 credits    ·  <b>₹250</b>\n"
        f"◈  Lifetime      ·  <b>₹1599</b>\n\n"
        f"{DIVIDER}\n"
        f"<i>◌  Tap a plan below to see payment details</i>",
        reply_markup=get_buy_keyboard()
    )

def show_referral_info(chat_id):
    username = get_bot_username()
    link = f"https://t.me/{username}?start=ref_{chat_id}"
    u = get_user(chat_id)
    ref_count = u.get('referral_count', 0) if u else 0
    earned = ref_count
    send_telegram_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>〔 Referral 〕</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"◈  Friends joined  ·  {ref_count}\n"
        f"◈  Credits earned  ·  {earned}\n\n"
        f"{DIVIDER}\n"
        f"<i>◌  Share your link — earn +1 credit per friend who joins</i>"
    )

def channel_gate(chat_id):
    if is_channel_member(chat_id):
        return True
    send_telegram_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>〔 Channel Required 〕</b>\n\n"
        f"▸  Join <b>{CHANNEL_USERNAME}</b> to use this bot.\n\n"
        f"{DIVIDER}\n"
        f"<i>◌  Tap Join below, then confirm with the button.</i>",
        reply_markup=get_join_keyboard()
    )
    return False

def credit_gate(chat_id):
    if has_credits(chat_id):
        return True
    send_telegram_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>〔 No Credits 〕</b>\n\n"
        f"◈  Balance  ·  <b>0</b>\n\n"
        f"▸  Tap <b>◇ Buy Credits</b> to purchase a plan.\n"
        f"▸  Tap <b>◇ Referral</b> to earn credits free.\n\n"
        f"{DIVIDER}"
    )
    return False

# ============== TELEGRAM BOT CALLBACK & MESSAGE HANDLERS ==============
def handle_callback(chat_id, callback_query_id, data):
    answer_callback_query(callback_query_id)
    ensure_user(chat_id)

    if data != 'check_join':
        is_member = enforce_channel_membership(chat_id)
        if not is_member:
            channel_gate(chat_id)
            return

    if data == 'check_join':
        if is_channel_member(chat_id):
            is_new = ensure_user(chat_id)
            cr = get_credits(chat_id)
            cr_display = "Lifetime" if cr == float('inf') else str(int(cr))
            send_telegram_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
                f"<b>e-Aadhaar PDF  —  straight to Telegram</b>\n\n"
                f"◈  Source    ·  Official UIDAI portal\n"
                f"◈  Delivery  ·  Auto-unlocked, no password\n"
                f"◈  Methods   ·  Mobile  ·  Aadhaar  ·  EID\n\n"
                f"{DIVIDER}\n"
                f"◈  Credits  ·  {cr_display}\n\n"
                f"<i>◌  Select a method below to begin.</i>",
                reply_markup=get_main_keyboard()
            )
        else:
            send_telegram_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>〔 Not Joined Yet 〕</b>\n\n"
                f"✗  Channel membership not detected.\n\n"
                f"<i>◌  Join the channel, then tap the button again.</i>",
                reply_markup=get_join_keyboard()
            )
        return

    if data == 'cancel':
        clear_session(chat_id)
        send_telegram_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<i>✗  Session cancelled.</i>"
        )
        return

    if data == 'credits':
        show_credits_info(chat_id)
        return

    if data == 'buy':
        show_buy_menu(chat_id)
        return

    if data == 'referral':
        show_referral_info(chat_id)
        return

    if data.startswith('buy_'):
        plan_key = data.split('_')[1]
        plan = PLANS.get(plan_key)
        if not plan:
            return
        label = "Lifetime" if plan['lifetime'] else f"{plan['credits']} credits"
        send_telegram_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>〔 Payment — {plan['price']} 〕</b>\n\n"
            f"◈  Plan    ·  {label}\n"
            f"◈  Amount  ·  <b>{plan['price']}</b>\n\n"
            f"{DIVIDER}\n"
            f"▸  Message <b>{OWNER_USERNAME}</b> to pay\n"
            f"▸  Include your User ID in the message\n\n"
            f"◈  Your ID  ·  <code>{chat_id}</code>\n\n"
            f"{DIVIDER}"
        )
        return

def handle_owner_command(chat_id, text):
    parts = text.strip().split()

    if parts[0] == '/send' and len(parts) == 3 and parts[1] == 'all':
        try:
            amount = int(parts[2])
            users_map = all_users()
            if not users_map:
                send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n⚠️  कोई यूज़र नहीं मिला।")
                return True

            count = 0
            for uid in users_map.keys():
                if amount == -1:
                    add_credits(uid, 0, make_lifetime=True)
                    gift_text = "Lifetime"
                else:
                    add_credits(uid, amount)
                    gift_text = f"{amount} Credits"

                try:
                    send_telegram_message(
                        uid,
                        f"{BOT_NAME}\n{DIVIDER}\n"
                        f"🎁 <b>Gift from Admin!</b>\n\n"
                        f"You've Received <b>{gift_text}</b> Free\n\n"
                        f"💬 Enjoy....."
                    )
                    count += 1
                except Exception:
                    continue

            send_telegram_message(
                chat_id,
                f"{BOT_NAME}\n{DIVIDER}\n"
                f"<b>[ broadcast credits ]</b>\n\n"
                f"◆  Sent <b>{amount if amount != -1 else 'Lifetime'}</b>  to  <b>{count}</b>  users."
            )
        except ValueError:
            send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n✗  Usage: /send all AMOUNT\n(-1 for lifetime)")
        return True

    if parts[0] == '/send' and len(parts) == 3:
        try:
            target_id = int(parts[1])
            amount    = int(parts[2])
            if amount == -1:
                add_credits(target_id, 0, make_lifetime=True)
                send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n<b>[ done ]</b>\n\n◆  Granted Lifetime to <code>{target_id}</code>")
                send_telegram_message(target_id,
                    f"{BOT_NAME}\n{DIVIDER}\n"
                    f"<b>[ credits received ]</b>\n\n"
                    f"◆  Plan     —  Lifetime\n"
                    f"◆  Status   —  Active\n\n"
                    f"{DIVIDER}",
                    reply_markup=get_main_keyboard()
                )
            else:
                add_credits(target_id, amount)
                send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n<b>[ done ]</b>\n\n◆  Sent {amount} credits to <code>{target_id}</code>")
                send_telegram_message(target_id,
                    f"{BOT_NAME}\n{DIVIDER}\n"
                    f"<b>[ credits received ]</b>\n\n"
                    f"◆  Credits  —  +{amount}\n"
                    f"◆  Balance  —  {int(get_credits(target_id))}\n\n"
                    f"{DIVIDER}",
                    reply_markup=get_main_keyboard()
                )
        except ValueError:
            send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n✗  Usage: /send USERID AMOUNT\n(-1 for lifetime)")
        return True

    if parts[0] == '/stats':
        data = all_users()
        total = len(data)
        lifetime_count = sum(1 for u in data.values() if u.get('lifetime'))
        total_credits  = sum(u.get('credits', 0) for u in data.values() if not u.get('lifetime'))
        send_telegram_message(
            chat_id,
            f"{BOT_NAME}\n{DIVIDER}\n"
            f"<b>[ stats ]</b>\n\n"
            f"◆  Total users    —  {total}\n"
            f"◆  Lifetime       —  {lifetime_count}\n"
            f"◆  Credits in use —  {total_credits}\n\n"
            f"{DIVIDER}"
        )
        return True

    if parts[0] == '/balance' and len(parts) == 2:
        try:
            uid = int(parts[1])
            cr  = get_credits(uid)
            cr_display = "Lifetime" if cr == float('inf') else str(int(cr))
            send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n<b>[ balance ]</b>\n\n◆  User    —  <code>{uid}</code>\n◆  Credits —  {cr_display}\n\n{DIVIDER}")
        except ValueError:
            send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n✗  Usage: /balance USERID")
        return True

    if parts[0] == '/broadcast':
        msg = text.replace('/broadcast', '').strip()
        if not msg:
            send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n✗  Usage: /broadcast Your message here")
            return True
        data = all_users()
        if not data:
            send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n⚠️  कोई यूज़र नहीं मिला।")
            return True
        sent = 0
        for uid in data.keys():
            try:
                send_telegram_message(uid, msg)
                sent += 1
            except Exception:
                continue
        send_telegram_message(chat_id, f"{BOT_NAME}\n{DIVIDER}\n<b>[ broadcast ]</b>\n\n◆  Sent to {sent} users.")
        return True

    return False

def handle_message(chat_id, message_text):
    logger.info(f"Msg [{chat_id}]: {message_text[:60]}")
    ensure_user(chat_id)

    is_member = enforce_channel_membership(chat_id)
    if not is_member:
        channel_gate(chat_id)
        return

    msg_lower = message_text.strip().lower()
    if msg_lower.startswith('/create') or msg_lower == '🔑 create account':
        u = get_user(chat_id)
        if u and u.get('password'):
            send_telegram_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>〔 Account Already Exists 〕</b>\n\n"
                f"◈  User ID   ·  <code>{chat_id}</code>\n"
                f"◈  Password  ·  <code>{u['password']}</code>\n\n"
                f"<i>◌  Use the details above to login to the website.</i>\n"
                f"<i>◌  To view details again, send /myacc</i>"
            )
            return

        chars = string.ascii_letters + string.digits
        new_pwd = ''.join(random.choice(chars) for _ in range(8))

        uid = str(chat_id)
        users = load_users()
        if uid not in users:
            users[uid] = {
                'credits': 1, 'lifetime': False, 'referred_by': None,
                'referral_count': 0, 'joined': datetime.now().isoformat()
            }
        users[uid]['password'] = new_pwd
        users[uid]['credits'] = 1
        users[uid]['lifetime'] = False
        save_users(users)

        send_telegram_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>〔 Account Created  ✓ 〕</b>\n\n"
            f"◈  User ID   ·  <code>{chat_id}</code>\n"
            f"◈  Password  ·  <code>{new_pwd}</code>\n\n"
            f"<i>◌  Use these credentials to log in to the portal.</i>\n"
            f"<i>◌  Note: Your starting balance is 1 credit.</i>"
        )
        return

    if msg_lower.startswith('/myacc') or msg_lower == '👤 my account':
        u = get_user(chat_id)
        if not u or not u.get('password'):
            send_telegram_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>〔 No Account Found 〕</b>\n\n"
                f"▸  Your website login account has not been created yet.\n\n"
                f"<i>◌  Send /create to generate your User ID and Password.</i>"
            )
            return

        cr = get_credits(chat_id)
        cr_display = "Lifetime" if cr == float('inf') else str(int(cr))

        send_telegram_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>〔 Account Details 〕</b>\n\n"
            f"◈  User ID   ·  <code>{chat_id}</code>\n"
            f"◈  Password  ·  <code>{u['password']}</code>\n"
            f"◈  Credits   ·  <b>{cr_display}</b>\n\n"
            f"{DIVIDER}"
        )
        return

    if int(chat_id) == OWNER_ID if str(chat_id).isdigit() else False:
        if message_text.startswith('/') and handle_owner_command(chat_id, message_text):
            return

    send_telegram_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"Please use the menu buttons below to manage your account.\n\n"
        f"🔑 <b>Create Account</b>  —  Get your login credentials\n"
        f"👤 <b>My Account</b>  —  View details and balance\n\n"
        f"<i>◌ Note: Aadhaar search and download functions are available on the website portal.</i>",
        reply_markup=get_main_keyboard()
    )

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {'timeout': 30, 'allowed_updates': ['message', 'callback_query', 'chat_member']}
    if offset:
        params['offset'] = offset
    try:
        response = get_telegram_session().get(url, params=params, timeout=35)
        result = response.json()
        if result.get('ok'):
            return result.get('result', [])
        else:
            logger.error(f"Telegram API error: {result}")
            return []
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return []

def run_telegram_bot():
    logger.info(f"{BOT_NAME} Telegram Polling starting...")
    setup_proxy()

    try:
        r = get_telegram_session().get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10
        )
        bot_info = r.json()
        if bot_info.get('ok'):
            global _bot_username
            _bot_username = bot_info['result']['username']
            logger.info(f"Bot Online: @{_bot_username}")
        else:
            logger.error(f"Bot auth failed: {bot_info}")
            return
    except Exception as e:
        logger.error(f"Bot startup error: {e}")
        return

    t = threading.Thread(target=_cleanup_sessions, daemon=True)
    t.start()

    last_update_id = 0

    while True:
        try:
            updates = get_updates(last_update_id + 1)

            for update in updates:
                last_update_id = update.get('update_id')

                if 'chat_member' in update:
                    cm = update['chat_member']
                    user = cm.get('new_chat_member', {}).get('user', {})
                    user_id = user.get('id')
                    status = cm.get('new_chat_member', {}).get('status')
                    if user_id and status in ('left', 'kicked'):
                        enforce_channel_membership(user_id)

                elif 'callback_query' in update:
                    cq = update['callback_query']
                    cid = cq['message']['chat']['id']
                    cqid = cq['id']
                    data = cq.get('data', '')
                    handle_callback(cid, cqid, data)

                elif 'message' in update:
                    msg = update['message']
                    cid = msg['chat']['id']
                    text = msg.get('text', '').strip()
                    if not text:
                        continue

                    if text.startswith('/start'):
                        parts = text.split()
                        referrer_id = None
                        if len(parts) > 1 and parts[1].startswith('ref_'):
                            try:
                                referrer_id = int(parts[1][4:])
                            except ValueError:
                                pass

                        if not is_channel_member(cid):
                            send_telegram_message(
                                cid,
                                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                                f"<b>〔 Channel Required 〕</b>\n\n"
                                f"▸  Join <b>{CHANNEL_USERNAME}</b> to use this bot.\n\n"
                                f"{DIVIDER}\n"
                                f"<i>◌  Tap the button below after joining.</i>",
                                reply_markup=get_join_keyboard()
                            )
                            continue

                        is_new = ensure_user(cid, referrer_id)
                        clear_session(cid)
                        cr = get_credits(cid)
                        cr_display = "Lifetime" if cr == float('inf') else str(int(cr))
                        bonus_line = f"\n◈  Bonus        ·  <b>+1 credit for joining!</b>" if is_new else ""
                        send_telegram_message(
                            cid,
                            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
                            f"<b>e-Aadhaar PDF  —  straight to Telegram</b>\n\n"
                            f"◈  Source    ·  Official UIDAI portal\n"
                            f"◈  Delivery  ·  Auto-unlocked, no password\n"
                            f"◈  Methods   ·  Mobile  ·  Aadhaar  ·  EID"
                            f"{bonus_line}\n\n"
                            f"{DIVIDER}\n"
                            f"◈  Credits  ·  {cr_display}\n\n"
                            f"<i>◌  Select a method below to begin.</i>",
                            reply_markup=get_main_keyboard()
                        )
                    else:
                        handle_message(cid, text)

            time.sleep(1)

        except Exception as e:
            logger.error(f"Telegram main loop error: {e}")
            time.sleep(5)

# Start background Telegram bot polling thread automatically
bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()

# ============== APPLICATION ENTRYPOINT ==============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info("=" * 60)
    logger.info(f"  e-Aadhaar Web Portal & Telegram Bot Server Started")
    logger.info(f"  Listening on port {port}")
    logger.info("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)
