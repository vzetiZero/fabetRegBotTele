import os
import random
import threading
import time
import requests
from queue import Queue

class ProxyManager:
    def __init__(self, proxy_file="proxy.txt", env_file=".env", min_refresh_interval=30):
        self.proxy_file = proxy_file
        self.env_file = env_file
        self.min_refresh_interval = min_refresh_interval

        self.proxies = []
        self.proxy_queue = Queue()
        self.lock = threading.Lock()

        self.api_key = self._load_env_value("PROXYFB_API_KEY")
        self.location = self._load_env_value("PROXYFB_LOCATION")

        self.current_proxy = None
        self.current_location = None
        self.current_timeout = None
        self.next_change_at = 0.0
        self.last_refresh_at = 0.0
        self.last_error = ""
        self.last_proxy_response = None  # Lưu response cuối

        if not self.api_key:
            self.load_proxies(proxy_file)

    def _load_env_value(self, key):
        env_value = os.getenv(key, "").strip()
        if env_value:
            return env_value

        if not os.path.exists(self.env_file):
            return ""

        try:
            with open(self.env_file, "r", encoding="utf-8") as file:
                for raw_line in file:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    env_key, env_value = line.split("=", 1)
                    if env_key.strip() == key:
                        return env_value.strip().strip('"').strip("'")
        except Exception:
            return ""
        return ""

    def load_proxies(self, proxy_file):
        self.proxies = []
        self.proxy_queue = Queue()
        try:
            with open(proxy_file, "r", encoding="utf-8") as file:
                for line in file:
                    proxy = line.strip()
                    if proxy and not proxy.startswith("#"):
                        self.proxies.append(proxy)

            print(f"[+] Loaded {len(self.proxies)} proxies from {proxy_file}")

            for proxy in self.proxies:
                self.proxy_queue.put(proxy)
        except FileNotFoundError:
            print(f"[-] Proxy file not found: {proxy_file}")
            self.proxies = []

    def _request_proxyfb(self, endpoint, params=None):
        """Gửi request tới ProxyFB API"""
        response = requests.get(endpoint, params=params or {}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid ProxyFB response")
        return data

    def _set_current_proxy(self, data):
        """Cập nhật proxy hiện tại từ response data"""
        proxy = str(data.get("proxy", "")).strip()
        if not proxy:
            return None

        now = time.time()
        
        # Parse next_change - có thể là số giây
        next_change = str(data.get("next_change", "0")).strip()
        try:
            next_change_seconds = max(int(float(next_change)), 0)
        except ValueError:
            next_change_seconds = 0

        timeout = str(data.get("timeout", "")).strip()

        self.current_proxy = proxy
        self.current_location = data.get("location")
        self.current_timeout = timeout
        self.last_refresh_at = now
        self.next_change_at = now + next_change_seconds if next_change_seconds > 0 else 0
        self.last_error = ""
        self.last_proxy_response = data
        
        print(f"[Proxy] Đã lấy proxy mới: {proxy}, next_change: {next_change_seconds}s")
        return proxy

    def _get_current_proxy_from_api(self):
        """Lấy proxy hiện tại từ API"""
        try:
            data = self._request_proxyfb(
                "http://api.proxyfb.com/api/getProxy.php",
                {"key": self.api_key},
            )
            if data.get("success"):
                return self._set_current_proxy(data)
            self.last_error = str(data.get("description", "ProxyFB getProxy failed"))
            return None
        except Exception as error:
            self.last_error = f"Lỗi getProxy: {str(error)}"
            return None

    def _change_proxy_from_api(self, max_retries=3):
        """
        Đổi proxy mới từ API
        Nếu trả về proxy cũ, retry sau 5s
        """
        params = {"key": self.api_key}
        location = str(self.location or "").strip()
        if location:
            params["location"] = location

        old_proxy = self.current_proxy
        
        for attempt in range(max_retries):
            try:
                data = self._request_proxyfb(
                    "http://api.proxyfb.com/api/changeProxy.php", 
                    params
                )
                
                if data.get("success"):
                    new_proxy = str(data.get("proxy", "")).strip()
                    
                    # Kiểm tra nếu proxy mới trùng với proxy cũ
                    if old_proxy and new_proxy == old_proxy:
                        print(f"[Proxy] Lần {attempt + 1}: changeProxy trả về proxy cũ, đợi 5s...")
                        time.sleep(5)
                        continue
                    
                    # Lấy được proxy mới thành công
                    return self._set_current_proxy(data)
                else:
                    self.last_error = str(data.get("description", "ProxyFB changeProxy failed"))
                    
            except Exception as error:
                self.last_error = f"Lỗi changeProxy lần {attempt + 1}: {str(error)}"
                if attempt < max_retries - 1:
                    print(f"[Proxy] Lỗi, thử lại sau 5s...")
                    time.sleep(5)
        
        # Nếu không lấy được proxy mới, trả về proxy cũ nếu có
        if self.current_proxy:
            print(f"[Proxy] Không lấy được proxy mới, giữ proxy cũ: {self.current_proxy}")
            return self.current_proxy
        
        return None

    def _get_proxy_from_proxyfb(self, force_refresh=False):
        """Lấy proxy từ ProxyFB với logic refresh"""
        now = time.time()
        
        # Kiểm tra nếu chưa đến thời gian refresh
        if self.current_proxy and not force_refresh:
            # Chưa đủ thời gian giữa các lần refresh
            if now - self.last_refresh_at < self.min_refresh_interval:
                return self.current_proxy
            
            # Chưa đến thời gian next_change
            if self.next_change_at and now < self.next_change_at:
                return self.current_proxy

        # Lấy proxy mới
        if not self.current_proxy or force_refresh:
            # Lần đầu hoặc force refresh: lấy proxy mới
            try:
                proxy = self._change_proxy_from_api()
                if proxy:
                    return proxy
            except Exception as error:
                self.last_error = str(error)

        # Fallback: lấy proxy hiện tại nếu có
        if self.current_proxy:
            return self.current_proxy

        # Cuối cùng: thử getProxy
        try:
            return self._get_current_proxy_from_api()
        except Exception as error:
            self.last_error = str(error)
            return None

    def get_proxy(self):
        """Lấy proxy (thread-safe)"""
        with self.lock:
            if self.api_key:
                return self._get_proxy_from_proxyfb(force_refresh=False)
            
            if not self.proxies:
                return None
            if not self.proxy_queue.empty():
                proxy = self.proxy_queue.get()
                self.proxy_queue.put(proxy)
                return proxy
            return random.choice(self.proxies)

    def refresh_proxy(self):
        """Force refresh proxy mới"""
        with self.lock:
            if self.api_key:
                return self._get_proxy_from_proxyfb(force_refresh=True)
            return self.get_proxy()

    def get_proxy_round_robin(self):
        return self.get_proxy()

    def get_random_proxy(self):
        return self.get_proxy()

    def get_proxy_count(self):
        if self.api_key:
            return 1 if self.get_proxy() else 0
        return len(self.proxies)

    def refresh_proxy_guaranteed(self, max_wait=30, callback=None):
        """Refresh proxy đảm bảo lấy được proxy mới"""
        old_proxy = self.current_proxy
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            if callback:
                callback(f"Đang refresh proxy... (đã dùng {int(time.time() - start_time)}s)")
            
            new_proxy = self.refresh_proxy()
            
            if new_proxy and new_proxy != old_proxy:
                if callback:
                    callback(f"✅ Đã lấy proxy mới: {new_proxy}")
                return new_proxy
            
            time.sleep(3)
        
        if self.current_proxy:
            if callback:
                callback(f"⚠️ Không lấy được proxy mới, giữ proxy cũ: {self.current_proxy}")
            return self.current_proxy
        
        return None
    def mark_proxy_failed(self, proxy):
        with self.lock:
            if self.api_key:
                if self.current_proxy == proxy:
                    print(f"[Proxy] Đánh dấu proxy {proxy} failed, sẽ lấy proxy mới")
                    self.current_proxy = None
                    self.current_location = None
                    self.current_timeout = None
                    self.next_change_at = 0.0
                    self.last_refresh_at = 0.0
                return

            if proxy in self.proxies:
                self.proxies.remove(proxy)
                print(f"[-] Removed failed proxy {proxy}. Remaining: {len(self.proxies)}")