import requests
import time
from fake_useragent import UserAgent

from config import DEPOSIT_API, LOGIN_API, TARGET_URL


PAYEDCO_API = "https://fabet.menu/api/v2/payment/3rd/payedco"
REQUEST_DELAY_SECONDS = 3  # Giảm delay để tăng tốc
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
                callback(f"Đang đăng nhập: {username}")

            response = session.post(LOGIN_API, json=login_payload, timeout=30)
            
            # Kiểm tra status code
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"

            data = response.json()
            if data.get("status") == "OK" and data.get("success") and data.get("code") == 200:
                if "user" in session.cookies:
                    if callback:
                        callback(f"Đăng nhập thành công: {username}")
                    return True, session
                return False, "Không nhận được cookie xác thực"

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
            
            # Kiểm tra status code - nếu không phải 200 thì báo lỗi
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Request {request_index}/{total_requests} HTTP {response.status_code}",
                    "status_code": response.status_code
                }

            data = response.json()
            if not (data.get("success") and data.get("status") == "OK"):
                return {
                    "success": False,
                    "error": data.get("message") or data.get("msg") or f"Request {request_index}/{total_requests} failed",
                    "status_code": response.status_code
                }

            result = self.extract_bank_info(data)
            if not result:
                return {
                    "success": False,
                    "error": f"Request {request_index}/{total_requests} không có dữ liệu bank",
                    "status_code": response.status_code
                }

            result["request_name"] = request_config["name"]
            result["request_index"] = request_index
            result["request_payload"] = dict(request_config["payload"])

            if callback:
                callback(f"✅ Request {request_index}/{total_requests} thành công: {result['formatted']}")

            return result
        except Exception as error:
            return {
                "success": False,
                "error": f"Request {request_index}/{total_requests} exception: {str(error)}",
                "status_code": 0
            }

    def fetch_bank_for_account(self, account, amount=300000, callback=None, max_retries=3):
        """
        Lấy thông tin bank cho 1 account
        Sẽ lặp lại toàn bộ chuỗi request đến khi thành công hoặc hết số lần retry
        Mỗi lần retry sẽ dùng proxy mới (được xử lý ở bên ngoài)
        """
        if callback:
            callback(f"🎯 Bắt đầu lấy bank cho {account.get('username')}, tối đa {max_retries} lần thử")
        
        for attempt in range(1, max_retries + 1):
            if callback:
                callback(f"🔄 Lần thử {attempt}/{max_retries} cho {account.get('username')}")
            
            # Kiểm tra proxy
            if self.proxy:
                if not self.test_proxy():
                    error_msg = f"Proxy {self.proxy} không hoạt động"
                    if callback:
                        callback(f"❌ {error_msg}")
                    if attempt < max_retries:
                        continue
                    return False, error_msg
            
            # Đăng nhập
            success, result = self.login(account["username"], account["password"], callback)
            if not success:
                if callback:
                    callback(f"❌ Đăng nhập thất bại lần {attempt}: {result}")
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                return False, f"Đăng nhập thất bại sau {max_retries} lần: {result}"
            
            session = result
            all_results = []
            total_requests = len(REQUEST_SEQUENCE)
            request_success = True
            
            # Thực hiện chuỗi request
            for index, request_config in enumerate(REQUEST_SEQUENCE, start=1):
                bank_info = self.send_deposit_request(session, request_config, index, total_requests, callback=callback)
                
                # Nếu request thất bại
                if not bank_info.get("success"):
                    status_code = bank_info.get("status_code", 0)
                    error_msg = bank_info.get("error", "Unknown error")
                    
                    if callback:
                        callback(f"❌ Request thất bại: {error_msg}")
                    
                    # Nếu status code là 401 (unauthorized) hoặc 403, cần đăng nhập lại
                    if status_code in [401, 403]:
                        if callback:
                            callback(f"⚠️ Session hết hạn, sẽ thử lại lần {attempt + 1}")
                        request_success = False
                        break
                    
                    # Các lỗi khác
                    if attempt < max_retries:
                        request_success = False
                        break
                    else:
                        return False, error_msg
                
                all_results.append(bank_info)
                
                # Delay giữa các request
                if index < total_requests:
                    if callback:
                        callback(f"⏳ Chờ {REQUEST_DELAY_SECONDS}s trước request tiếp theo...")
                    time.sleep(REQUEST_DELAY_SECONDS)
            
            # Nếu hoàn thành tất cả request thành công
            if request_success and all_results:
                final_result = dict(all_results[-1])
                final_result["results"] = all_results
                
                if callback:
                    callback(f"✅ Hoàn thành lấy bank cho {account.get('username')}")
                
                return True, final_result
            
            # Nếu thất bại và còn lần thử
            if attempt < max_retries:
                if callback:
                    callback(f"⏳ Chờ 3s trước khi thử lại lần {attempt + 1}...")
                time.sleep(3)
        
        return False, f"Không thể lấy bank sau {max_retries} lần thử"

    def fetch_bank_with_retry_and_new_proxy(self, account, amount=300000, callback=None, 
                                            max_retries=3, proxy_manager=None):
        """
        Lấy bank với cơ chế tự động lấy proxy mới mỗi lần retry
        """
        if not proxy_manager:
            # Nếu không có proxy_manager, dùng proxy hiện tại
            return self.fetch_bank_for_account(account, amount, callback, max_retries)
        
        for attempt in range(1, max_retries + 1):
            if callback:
                callback(f"🔄 Lấy bank cho {account.get('username')} - Lần {attempt}/{max_retries}")
            
            # Lấy proxy mới cho mỗi lần thử
            if attempt > 1 or not self.proxy:
                new_proxy = proxy_manager.refresh_proxy()
                if new_proxy:
                    self.proxy = new_proxy
                    if callback:
                        callback(f"🌐 Đã đổi proxy mới: {self.proxy}")
                else:
                    if callback:
                        callback(f"⚠️ Không thể lấy proxy mới, dùng proxy cũ nếu có")
            
            # Thử lấy bank
            success, result = self.fetch_bank_for_account(account, amount, callback, max_retries=1)
            
            if success:
                return True, result
            
            # Nếu thất bại và còn lần thử, đánh dấu proxy lỗi
            if attempt < max_retries and self.proxy:
                proxy_manager.mark_proxy_failed(self.proxy)
                if callback:
                    callback(f"🗑️ Đã đánh dấu proxy {self.proxy} là lỗi")
                time.sleep(2)
        
        return False, f"Thất bại sau {max_retries} lần thử với proxy khác nhau"