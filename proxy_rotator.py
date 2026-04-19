import time
import threading
import queue
import random
from datetime import datetime
from proxy_manager import ProxyManager

class ProxyRotator:
    """Quản lý xoay vòng proxy tự động"""
    
    def __init__(self, proxy_manager, min_delay_between_requests=3):
        self.proxy_manager = proxy_manager
        self.min_delay = min_delay_between_requests
        self.proxy_queue = queue.Queue()
        self.used_proxies = {}
        self.lock = threading.Lock()
        self.last_request_time = 0
        
    def get_fresh_proxy(self, force_new=True):
        """
        Lấy proxy mới, đảm bảo không trùng với proxy đã dùng gần đây
        force_new: ép lấy proxy mới hoàn toàn
        """
        with self.lock:
            # Kiểm tra delay giữa các request
            now = time.time()
            time_since_last = now - self.last_request_time
            if time_since_last < self.min_delay:
                wait_time = self.min_delay - time_since_last
                time.sleep(wait_time)
            
            max_attempts = 10
            for attempt in range(max_attempts):
                # Lấy proxy mới từ manager
                if force_new:
                    proxy = self.proxy_manager.refresh_proxy()
                else:
                    proxy = self.proxy_manager.get_proxy()
                
                if not proxy:
                    return None
                
                # Kiểm tra xem proxy đã dùng gần đây chưa (trong 5 phút)
                if proxy in self.used_proxies:
                    last_used = self.used_proxies[proxy]
                    if now - last_used < 300:  # 5 phút
                        if attempt < max_attempts - 1:
                            continue
                
                # Đánh dấu đã dùng
                self.used_proxies[proxy] = now
                self.last_request_time = now
                
                # Dọn dẹp cache (xóa proxy cũ hơn 10 phút)
                self._cleanup_old_proxies(now)
                
                return proxy
            
            return None
    
    def _cleanup_old_proxies(self, current_time):
        """Xóa proxy đã dùng lâu"""
        to_delete = []
        for proxy, last_used in self.used_proxies.items():
            if current_time - last_used > 600:  # 10 phút
                to_delete.append(proxy)
        for proxy in to_delete:
            del self.used_proxies[proxy]
    
    def mark_proxy_failed(self, proxy):
        """Đánh dấu proxy bị lỗi"""
        with self.lock:
            if proxy in self.used_proxies:
                del self.used_proxies[proxy]
            self.proxy_manager.mark_proxy_failed(proxy)
    
    def get_stats(self):
        """Lấy thống kê"""
        with self.lock:
            return {
                "used_proxies_count": len(self.used_proxies),
                "available_proxies": self.proxy_manager.get_proxy_count(),
                "current_proxy": self.proxy_manager.current_proxy,
                "next_change_at": self.proxy_manager.next_change_at
            }
        

    def get_proxy_forced_new(self, old_proxy=None):
        """
        BẮT BUỘC lấy proxy mới, không được trùng với proxy cũ
        """
        with self.lock:
            max_attempts = 10
            for attempt in range(max_attempts):
                # Refresh để lấy proxy mới
                new_proxy = self.proxy_manager.refresh_proxy()
                
                if not new_proxy:
                    if attempt < max_attempts - 1:
                        time.sleep(1)
                        continue
                    return None
                
                # Kiểm tra không trùng với proxy cũ
                if old_proxy and new_proxy == old_proxy:
                    if attempt < max_attempts - 1:
                        time.sleep(2)  # Chờ 2s rồi thử lại
                        continue
                
                # Đánh dấu đã dùng
                now = time.time()
                self.used_proxies[new_proxy] = now
                self.last_request_time = now
                self._cleanup_old_proxies(now)
                
                return new_proxy
            
            return None