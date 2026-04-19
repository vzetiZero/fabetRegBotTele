import requests
import time
import random
import string
from fake_useragent import UserAgent
from config import *

class AccountCreator:
    def __init__(self, proxy=None):
        self.session = None
        self.captcha_token = None
        self.proxy = proxy
        
    def get_proxy_dict(self):
        """Chuyển proxy string thành dict cho requests"""
        if not self.proxy:
            return None
        
        parts = self.proxy.split(':')
        if len(parts) == 4:
            host, port, username, password = parts
            proxy_url = f"http://{username}:{password}@{host}:{port}"
            return {
                "http": proxy_url,
                "https": proxy_url
            }
        elif len(parts) == 2:
            host, port = parts
            proxy_url = f"http://{host}:{port}"
            return {
                "http": proxy_url,
                "https": proxy_url
            }
        return None
    
    def test_proxy(self):
        """Kiểm tra proxy có hoạt động không"""
        if not self.proxy:
            return True
        
        proxy_dict = self.get_proxy_dict()
        if not proxy_dict:
            return False
        
        try:
            response = requests.get('https://api.ipify.org?format=json', 
                                   proxies=proxy_dict, timeout=10)
            if response.status_code == 200:
                ip = response.json().get('ip')
                print(f"[+] Proxy {self.proxy} hoạt động, IP: {ip}")
                return True
        except Exception as e:
            print(f"[-] Proxy {self.proxy} lỗi: {str(e)}")
            return False
        
        return False
        
    def random_username(self, length=10):
        chars = string.ascii_lowercase + string.digits
        return ''.join(random.choices(chars, k=length))

    def random_password(self, length=12):
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choices(chars, k=length))

    def random_phone(self):
        prefixes = ['03', '05', '07', '08', '09']
        prefix = random.choice(prefixes)
        number = ''.join(random.choices(string.digits, k=8))
        return prefix + number

    def get_public_ip(self):
        """Lấy IP thực tế"""
        try:
            proxies = self.get_proxy_dict()
            response = requests.get('https://api.ipify.org?format=json', timeout=10, proxies=proxies)
            return response.json()['ip']
        except:
            return f"14.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}"

    def solve_captcha(self, callback=None):
        """Giải captcha bằng CapMonster"""
        
        create_task_payload = {
            "clientKey": CAPMONSTER_API_KEY,
            "task": {
                "type": "TurnstileTaskProxyless",
                "websiteURL": TARGET_URL,
                "websiteKey": SITE_KEY,
            }
        }
        
        if self.proxy:
            proxy_parts = self.proxy.split(':')
            if len(proxy_parts) >= 2:
                create_task_payload["task"]["proxyType"] = "http"
                create_task_payload["task"]["proxyAddress"] = proxy_parts[0]
                create_task_payload["task"]["proxyPort"] = int(proxy_parts[1])
                if len(proxy_parts) == 4:
                    create_task_payload["task"]["proxyLogin"] = proxy_parts[2]
                    create_task_payload["task"]["proxyPassword"] = proxy_parts[3]
        
        try:
            if callback:
                callback("Đang tạo task captcha...")
            
            response = requests.post("https://api.capmonster.cloud/createTask", json=create_task_payload, timeout=30)
            response_data = response.json()
            
            if response_data.get("errorId") != 0:
                return None
                
            task_id = response_data.get("taskId")
            
            if callback:
                callback(f"Task ID: {task_id}, đang chờ giải...")
            
            get_result_payload = {
                "clientKey": CAPMONSTER_API_KEY,
                "taskId": task_id
            }
            
            for attempt in range(30):
                time.sleep(3)
                result_response = requests.post("https://api.capmonster.cloud/getTaskResult", json=get_result_payload, timeout=30)
                result_data = result_response.json()
                
                if result_data.get("status") == "ready":
                    token = result_data["solution"]["token"]
                    if callback:
                        callback("✅ Lấy token captcha thành công!")
                    return token
                    
            return None
            
        except Exception as e:
            if callback:
                callback(f"Lỗi captcha: {str(e)}")
            return None

    def create_session(self):
        """Tạo session mới với proxy"""
        session = requests.Session()
        ua = UserAgent()
        
        proxy_dict = self.get_proxy_dict()
        if proxy_dict:
            session.proxies.update(proxy_dict)
        
        session.headers.update({
            "User-Agent": ua.random,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://fabet.menu",
            "Referer": TARGET_URL
        })
        
        return session

    def register(self, username, phone, password, captcha_token, session, callback=None):
        """Đăng ký tài khoản - CHỈ ĐĂNG KÝ, KHÔNG LOGIN"""
        
        session.cookies.set("turnstileToken", captcha_token, domain=".fabet.menu", path="/")
        
        register_payload = {
            "username": username,
            "phone": phone,
            "password": password,
            "confirmPassword": password,
            "turnstileToken": "",
            "ip": self.get_public_ip(),
            "os": "Windows 10",
            "device": "desktop",
            "browser": "Chrome"
        }
        
        try:
            if callback:
                callback(f"Đang đăng ký: {username}")
            
            response = session.post(REGISTER_API, json=register_payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                # Đăng ký thành công khi status OK hoặc code 200
                if data.get("status") == "OK" or data.get("code") == 200:
                    if callback:
                        callback(f"✅ Đăng ký thành công: {username}")
                    return True, data
                else:
                    error_msg = data.get("message") or data.get("msg") or "Unknown error"
                    return False, error_msg
            else:
                return False, f"HTTP {response.status_code}"
                
        except Exception as e:
            return False, str(e)

    def register_only(self, amount=300000, callback=None):
        """CHỈ ĐĂNG KÝ TÀI KHOẢN, không lấy bank"""
        
        # Kiểm tra proxy
        if self.proxy:
            if not self.test_proxy():
                return None, f"Proxy {self.proxy} không hoạt động"
        
        # Tạo thông tin ngẫu nhiên
        username = self.random_username()
        phone = self.random_phone()
        password = self.random_password()
        
        if callback:
            callback(f"Thông tin: {username}|{phone}|{password}")
        
        # Giải captcha
        captcha_token = self.solve_captcha(callback)
        if not captcha_token:
            return None, "Không thể giải captcha"
        
        # Tạo session và đăng ký
        session = self.create_session()
        success, result = self.register(username, phone, password, captcha_token, session, callback)
        
        if not success:
            return None, result
        
        # Trả về thông tin tài khoản
        account_info = {
            "username": username,
            "phone": phone,
            "password": password,
            "proxy": self.proxy,
            "status": "registered"
        }
        
        return account_info, None