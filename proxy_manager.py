import random
import threading
from queue import Queue


class ProxyManager:
    def __init__(self, proxy_file="proxy.txt"):
        self.proxies = []
        self.proxy_queue = Queue()
        self.lock = threading.Lock()
        self.load_proxies(proxy_file)

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

    def get_proxy(self):
        with self.lock:
            if not self.proxies:
                return None
            if not self.proxy_queue.empty():
                proxy = self.proxy_queue.get()
                self.proxy_queue.put(proxy)
                return proxy
            return random.choice(self.proxies)

    def get_proxy_round_robin(self):
        with self.lock:
            if not self.proxies:
                return None
            if not self.proxy_queue.empty():
                proxy = self.proxy_queue.get()
                self.proxy_queue.put(proxy)
                return proxy
            return None

    def get_random_proxy(self):
        with self.lock:
            if not self.proxies:
                return None
            return random.choice(self.proxies)

    def get_proxy_count(self):
        return len(self.proxies)

    def mark_proxy_failed(self, proxy):
        with self.lock:
            if proxy in self.proxies:
                self.proxies.remove(proxy)
                print(f"[-] Removed failed proxy {proxy}. Remaining: {len(self.proxies)}")
