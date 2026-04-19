"""
Telegram notification helpers with persistent transaction dedupe.
"""

import json
import os
import time
from threading import RLock
from datetime import datetime

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramNotifier:
    """Send Telegram messages and persist sent transaction keys across runs."""

    _sent_lock = RLock()
    _sent_messages: dict[str, float] = {}
    _dedupe_ttl_seconds = 12 * 60 * 60
    _history_file = "data/sent_transactions.json"
    _transaction_history: set[str] | None = None

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    @classmethod
    def _ensure_parent_dir(cls) -> None:
        os.makedirs(os.path.dirname(cls._history_file), exist_ok=True)

    @classmethod
    def _load_transaction_history(cls) -> set[str]:
        if cls._transaction_history is not None:
            return cls._transaction_history

        cls._ensure_parent_dir()
        try:
            with open(cls._history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                cls._transaction_history = {str(item).strip() for item in data if str(item).strip()}
            else:
                cls._transaction_history = set()
        except FileNotFoundError:
            cls._transaction_history = set()
        except Exception:
            cls._transaction_history = set()
        return cls._transaction_history

    @classmethod
    def _save_transaction_history(cls) -> None:
        cls._ensure_parent_dir()
        history = sorted(cls._load_transaction_history())
        with open(cls._history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _normalize_part(value: str) -> str:
        return " ".join(str(value or "").strip().upper().split())

    @classmethod
    def _build_transaction_key(cls, bank_name: str, account_name: str, account_no: str) -> str:
        return "|".join(
            [
                cls._normalize_part(bank_name),
                cls._normalize_part(account_name),
                cls._normalize_part(account_no),
            ]
        )

    @classmethod
    def _cleanup_sent_messages(cls) -> None:
        now = time.time()
        expired_keys = [
            key for key, expires_at in cls._sent_messages.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            cls._sent_messages.pop(key, None)

    @classmethod
    def _reserve_message(cls, message: str) -> bool:
        with cls._sent_lock:
            cls._cleanup_sent_messages()
            if message in cls._sent_messages:
                return False
            cls._sent_messages[message] = time.time() + cls._dedupe_ttl_seconds
            return True

    @classmethod
    def _reserve_transaction_key(cls, transaction_key: str) -> bool:
        with cls._sent_lock:
            history = cls._load_transaction_history()
            if transaction_key in history:
                return False
            history.add(transaction_key)
            cls._save_transaction_history()
            return True

    @classmethod
    def _release_transaction_key(cls, transaction_key: str) -> None:
        with cls._sent_lock:
            history = cls._load_transaction_history()
            if transaction_key in history:
                history.remove(transaction_key)
                cls._save_transaction_history()

    def send_message(self, message: str) -> bool:
        """Send a raw Telegram message with in-memory short-term dedupe."""
        if not self.bot_token or not self.chat_id:
            return False
        if not self._reserve_message(message):
            print(f"Telegram duplicate skipped: {message}")
            return False
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            response = requests.post(self.api_url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
            with self._sent_lock:
                self._sent_messages.pop(message, None)
            return False
        except Exception as e:
            with self._sent_lock:
                self._sent_messages.pop(message, None)
            print(f"Telegram send error: {e}")
            return False

    def send_bank_info_only(self, bank_info: dict) -> bool:
        """Chỉ gửi thông tin bank đơn giản"""
        formatted = bank_info.get('formatted', '')
        if not formatted:
            return False
        
        # Kiểm tra trùng lặp
        if not self._reserve_transaction_key(formatted):
            print(f"Bank info duplicate skipped: {formatted}")
            return False
        
        # Gửi tin nhắn đơn giản
        result = self.send_message(formatted)
        if not result:
            self._release_transaction_key(formatted)
        return result

    def send_new_account(self, username: str, phone: str, password: str, bank_info: dict) -> bool:
        """Gửi thông tin bank (bỏ qua username, phone, password)"""
        return self.send_bank_info_only(bank_info)

    def send_error(self, error: str, step: str = "Đăng ký") -> bool:
        """Không gửi lỗi qua Telegram"""
        return False

    def send_bot_status(self, is_running: bool) -> bool:
        """Không gửi trạng thái bot"""
        return False

    def send_summary(self, total: int, success: int, failed: int) -> bool:
        """Không gửi tổng kết"""
        return False