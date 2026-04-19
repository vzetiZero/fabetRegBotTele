import time
import threading
from collections import deque
from datetime import datetime

class RateLimiter:
    """Giới hạn số lượng request trong khoảng thời gian"""
    
    def __init__(self, max_requests=3, time_window=30):
        """
        max_requests: số request tối đa
        time_window: khoảng thời gian (giây)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = threading.Lock()
    
    def can_execute(self):
        """Kiểm tra có thể thực hiện request không"""
        with self.lock:
            now = time.time()
            
            # Xóa các request cũ
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()
            
            # Kiểm tra số lượng
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            return False
    
    def wait_if_needed(self):
        """Chờ nếu cần thiết"""
        with self.lock:
            if len(self.requests) >= self.max_requests:
                oldest = self.requests[0]
                wait_time = self.time_window - (time.time() - oldest)
                if wait_time > 0:
                    return wait_time
            return 0
    
    def get_wait_time(self):
        """Lấy thời gian cần chờ (giây)"""
        with self.lock:
            if len(self.requests) >= self.max_requests:
                oldest = self.requests[0]
                wait_time = self.time_window - (time.time() - oldest)
                return max(0, wait_time)
            return 0
    
    def get_remaining_slots(self):
        """Số slot còn trống trong time window"""
        with self.lock:
            now = time.time()
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()
            return max(0, self.max_requests - len(self.requests))


class AccountRateLimiter:
    """Quản lý rate limit cho tạo tài khoản"""
    
    def __init__(self, accounts_per_window=3, time_window=30):
        self.limiter = RateLimiter(accounts_per_window, time_window)
        self.total_created = 0
        self.total_failed = 0
        self.lock = threading.Lock()
    
    def can_create_account(self):
        """Kiểm tra có thể tạo tài khoản không"""
        return self.limiter.can_execute()
    
    def wait_for_slot(self, callback=None):
        """Chờ đến khi có slot trống"""
        wait_time = self.limiter.get_wait_time()
        if wait_time > 0:
            if callback:
                callback(f"⏳ Đang trong giới hạn {self.limiter.max_requests} tk/{self.limiter.time_window}s, cần chờ {wait_time:.1f}s")
            time.sleep(wait_time)
            return True
        return True
    
    def get_status(self):
        """Lấy trạng thái hiện tại"""
        remaining = self.limiter.get_remaining_slots()
        wait_time = self.limiter.get_wait_time()
        
        with self.lock:
            return {
                "remaining_slots": remaining,
                "wait_time": wait_time,
                "total_created": self.total_created,
                "total_failed": self.total_failed,
                "max_per_window": self.limiter.max_requests,
                "time_window": self.limiter.time_window
            }
    
    def record_success(self):
        """Ghi nhận tạo thành công"""
        with self.lock:
            self.total_created += 1
    
    def record_failure(self):
        """Ghi nhận tạo thất bại"""
        with self.lock:
            self.total_failed += 1