import requests
import time
from fake_useragent import UserAgent

from config import DEPOSIT_API, LOGIN_API, TARGET_URL


PAYEDCO_API = "https://fabet.menu/api/v2/payment/3rd/payedco"
REQUEST_DELAY_SECONDS = 5
REQUEST_SEQUENCE = [
    {
        "name": "fpay-100k",
        "url": DEPOSIT_API,
        "payload": {"amount": 100000, "package_id": 1},
    },
    {
        "name": "payedco-200k",
        "url": PAYEDCO_API,
        "payload": {"amount": 200000, "type": "banking", "package_id": 1, "provider": "ROTATE"},
    },
    {
        "name": "fpay-300k",
        "url": DEPOSIT_API,
        "payload": {"amount": 300000, "package_id": 1},
    },
    {
        "name": "payedco-500k",
        "url": PAYEDCO_API,
        "payload": {"amount": 500000, "type": "banking", "package_id": 1, "provider": "ROTATE"},
    },
    {
        "name": "fpay-1m",
        "url": DEPOSIT_API,
        "payload": {"amount": 1000000, "package_id": 1},
    },
    {
        "name": "fpay-100k-repeat",
        "url": DEPOSIT_API,
        "payload": {"amount": 100000, "package_id": 1},
    },
]


class BankFetcher:
    def __init__(self, proxy=None):
        self.proxy = proxy

    def get_proxy_dict(self):
        if not self.proxy:
            return None

        parts = self.proxy.split(":")
        if len(parts) == 4:
            host, port, username, password = parts
            proxy_url = f"http://{username}:{password}@{host}:{port}"
            return {"http": proxy_url, "https": proxy_url}
        if len(parts) == 2:
            host, port = parts
            proxy_url = f"http://{host}:{port}"
            return {"http": proxy_url, "https": proxy_url}
        return None

    def test_proxy(self):
        if not self.proxy:
            return True

        proxy_dict = self.get_proxy_dict()
        if not proxy_dict:
            return False

        try:
            response = requests.get("https://api.ipify.org?format=json", proxies=proxy_dict, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def login(self, username, password, callback=None):
        session = requests.Session()
        ua = UserAgent()

        proxy_dict = self.get_proxy_dict()
        if proxy_dict:
            session.proxies.update(proxy_dict)

        session.headers.update(
            {
                "User-Agent": ua.random,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/json",
                "Origin": "https://fabet.menu",
                "Referer": TARGET_URL,
            }
        )

        login_payload = {"username": username, "password": password}

        try:
            if callback:
                callback(f"Dang dang nhap: {username}")

            response = session.post(LOGIN_API, json=login_payload, timeout=30)
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"

            data = response.json()
            if data.get("status") == "OK" and data.get("success") and data.get("code") == 200:
                if "user" in session.cookies:
                    if callback:
                        callback(f"Dang nhap thanh cong: {username}")
                    return True, session
                return False, "Khong nhan duoc cookie xac thuc"

            error_msg = data.get("message") or data.get("msg") or "Login failed"
            return False, error_msg
        except Exception as error:
            return False, str(error)

    def extract_bank_info(self, response_data):
        if not isinstance(response_data, dict):
            return None

        bank_data = response_data.get("data", [])
        if isinstance(bank_data, list) and bank_data:
            bank_info = bank_data[0]
        elif isinstance(bank_data, dict):
            bank_info = bank_data
        else:
            return None

        account_no = bank_info.get("bank_account_no") or bank_info.get("account_no") or bank_info.get("bankAccountNo")
        account_name = bank_info.get("bank_account_name") or bank_info.get("account_name") or bank_info.get("bankAccountName")
        bank_name = bank_info.get("bank_name") or bank_info.get("bank") or bank_info.get("bankName")

        if not account_no:
            return None

        return {
            "success": True,
            "bank_account_no": account_no or "N/A",
            "bank_account_name": account_name or "N/A",
            "bank_name": bank_name or "N/A",
            "formatted": f"{account_no or 'N/A'}|{account_name or 'N/A'}|{bank_name or 'N/A'}",
        }

    def send_deposit_request(self, session, request_config, request_index, total_requests, callback=None):
        session.headers.update({"Referer": "https://fabet.menu/account/deposit/bank-transfer"})

        try:
            if callback:
                callback(
                    f"Request {request_index}/{total_requests}: {request_config['name']} -> "
                    f"{request_config['url']} | payload={request_config['payload']}"
                )

            response = session.post(request_config["url"], json=request_config["payload"], timeout=30)
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Request {request_index}/{total_requests} HTTP {response.status_code}",
                }

            data = response.json()
            if not (data.get("success") and data.get("status") == "OK"):
                return {
                    "success": False,
                    "error": data.get("message") or data.get("msg") or f"Request {request_index}/{total_requests} failed",
                }

            result = self.extract_bank_info(data)
            if not result:
                return {
                    "success": False,
                    "error": f"Request {request_index}/{total_requests} khong co du lieu bank",
                }

            result["request_name"] = request_config["name"]
            result["request_index"] = request_index
            result["request_payload"] = dict(request_config["payload"])

            if callback:
                callback(f"Request {request_index}/{total_requests} thanh cong: {result['formatted']}")

            return result
        except Exception as error:
            return {
                "success": False,
                "error": f"Request {request_index}/{total_requests} exception: {str(error)}",
            }

    def fetch_bank_for_account(self, account, amount=300000, callback=None):
        if self.proxy and not self.test_proxy():
            return False, f"Proxy {self.proxy} khong hoat dong"

        success, result = self.login(account["username"], account["password"], callback)
        if not success:
            return False, result

        session = result
        all_results = []
        total_requests = len(REQUEST_SEQUENCE)

        for index, request_config in enumerate(REQUEST_SEQUENCE, start=1):
            bank_info = self.send_deposit_request(session, request_config, index, total_requests, callback=callback)
            if not bank_info.get("success"):
                return False, bank_info.get("error", "Khong lay duoc bank")

            all_results.append(bank_info)

            if index < total_requests:
                if callback:
                    callback(f"Cho {REQUEST_DELAY_SECONDS} giay truoc request tiep theo...")
                time.sleep(REQUEST_DELAY_SECONDS)

        final_result = dict(all_results[-1])
        final_result["results"] = all_results
        return True, final_result
