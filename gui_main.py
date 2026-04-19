import json
import os
import queue
import threading
import time
from datetime import datetime

import config
import register
import telegram_bot
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bank_fetcher import BankFetcher
from proxy_manager import ProxyManager
from register import AccountCreator
from telegram_bot import TelegramNotifier


class RegGameWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RegGame Bot - PySide6")
        self.resize(1280, 860)

        self.proxy_manager = ProxyManager()
        self.telegram = TelegramNotifier()
        self.bank_data_file = os.path.join("data", "bank_accounts.json")

        self.accounts_list = []
        self.accounts_lock = threading.Lock()
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()

        self.is_running = False
        self.stop_flag = False
        self.current_mode = None
        self.process_thread = None

        self.setup_ui()
        self.load_runtime_config_into_ui()
        self.apply_runtime_config(log_result=False)
        self.load_accounts_from_file()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queues)
        self.timer.start(100)

    @staticmethod
    def build_account_key(account):
        return "|".join(
            [
                account.get("username", ""),
                account.get("password", ""),
                account.get("phone", ""),
            ]
        )

    def load_bank_data(self):
        if not os.path.exists(self.bank_data_file):
            return {}
        try:
            with open(self.bank_data_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except Exception as error:
            self.log(f"Loi tai du lieu bank: {error}", "ERROR")
            return {}

    def save_bank_data(self, bank_data):
        try:
            os.makedirs(os.path.dirname(self.bank_data_file), exist_ok=True)
            with open(self.bank_data_file, "w", encoding="utf-8") as file:
                json.dump(bank_data, file, ensure_ascii=False, indent=2)
        except Exception as error:
            self.log(f"Loi luu du lieu bank: {error}", "ERROR")

    def save_bank_info_for_account(self, account):
        bank_data = self.load_bank_data()
        bank_data[self.build_account_key(account)] = {
            "bank_account_no": account.get("bank_account_no", ""),
            "bank_name": account.get("bank_name", ""),
            "bank_account_name": account.get("bank_account_name", ""),
        }
        self.save_bank_data(bank_data)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.register_tab = QWidget()
        self.accounts_tab = QWidget()
        self.log_tab = QWidget()

        self.tabs.addTab(self.register_tab, "Dang Ky")
        self.tabs.addTab(self.accounts_tab, "Tai Khoan")
        self.tabs.addTab(self.log_tab, "Log")

        self.setup_register_tab()
        self.setup_accounts_tab()
        self.setup_log_tab()

    def setup_register_tab(self):
        layout = QVBoxLayout(self.register_tab)

        config_box = QGroupBox("Cau Hinh Chay")
        config_layout = QGridLayout(config_box)
        layout.addWidget(config_box)

        config_layout.addWidget(QLabel("So luong tai khoan"), 0, 0)
        self.register_count_spin = QSpinBox()
        self.register_count_spin.setRange(1, 10000)
        self.register_count_spin.setValue(10)
        config_layout.addWidget(self.register_count_spin, 0, 1)

        config_layout.addWidget(QLabel("So luong dang ky"), 0, 2)
        self.register_threads_spin = QSpinBox()
        self.register_threads_spin.setRange(1, 100)
        self.register_threads_spin.setValue(5)
        config_layout.addWidget(self.register_threads_spin, 0, 3)

        config_layout.addWidget(QLabel("So luong lay bank"), 1, 0)
        self.bank_threads_spin = QSpinBox()
        self.bank_threads_spin.setRange(1, 100)
        self.bank_threads_spin.setValue(5)
        config_layout.addWidget(self.bank_threads_spin, 1, 1)

        config_layout.addWidget(QLabel("So tien nap"), 1, 2)
        self.bank_amount_spin = QSpinBox()
        self.bank_amount_spin.setRange(1000, 100000000)
        self.bank_amount_spin.setSingleStep(1000)
        self.bank_amount_spin.setValue(300000)
        config_layout.addWidget(self.bank_amount_spin, 1, 3)

        config_layout.addWidget(QLabel("Retry moi tai khoan"), 2, 0)
        self.bank_retry_spin = QSpinBox()
        self.bank_retry_spin.setRange(1, 100)
        self.bank_retry_spin.setValue(3)
        config_layout.addWidget(self.bank_retry_spin, 2, 1)

        self.register_use_proxy_check = QCheckBox("Su dung proxy khi dang ky")
        self.register_use_proxy_check.setChecked(True)
        config_layout.addWidget(self.register_use_proxy_check, 2, 2)

        self.bank_use_proxy_check = QCheckBox("Su dung proxy khi lay bank")
        self.bank_use_proxy_check.setChecked(True)
        config_layout.addWidget(self.bank_use_proxy_check, 2, 3)

        self.register_save_file_check = QCheckBox("Tu dong luu file")
        self.register_save_file_check.setChecked(True)
        config_layout.addWidget(self.register_save_file_check, 3, 0)

        self.bank_send_telegram_check = QCheckBox("Gui Telegram khi co bank moi")
        self.bank_send_telegram_check.setChecked(True)
        config_layout.addWidget(self.bank_send_telegram_check, 3, 1, 1, 2)

        self.proxy_count_label = QLabel(f"Proxy san sang: {self.proxy_manager.get_proxy_count()}")
        config_layout.addWidget(self.proxy_count_label, 3, 3)

        secret_box = QGroupBox("Cau Hinh Bao Mat")
        secret_layout = QFormLayout(secret_box)
        layout.addWidget(secret_box)

        self.capmonster_input, capmonster_row = self.create_secret_row("CAPMONSTER_API_KEY")
        secret_layout.addRow("CapMonster API Key", capmonster_row)

        self.telegram_token_input, token_row = self.create_secret_row("TELEGRAM_BOT_TOKEN")
        secret_layout.addRow("Telegram Bot Token", token_row)

        self.telegram_chat_id_input, chat_row = self.create_secret_row("TELEGRAM_CHAT_ID")
        secret_layout.addRow("Telegram Chat ID", chat_row)

        info_row = QHBoxLayout()
        layout.addLayout(info_row)

        self.apply_config_button = QPushButton("Ap dung cau hinh")
        self.apply_config_button.clicked.connect(self.on_apply_config_clicked)
        info_row.addWidget(self.apply_config_button)

        self.reload_proxy_button = QPushButton("Tai lai proxy")
        self.reload_proxy_button.clicked.connect(self.reload_proxies)
        info_row.addWidget(self.reload_proxy_button)
        info_row.addStretch()

        button_row = QHBoxLayout()
        layout.addLayout(button_row)

        self.register_start_button = QPushButton("Bat dau dang ky")
        self.register_start_button.clicked.connect(self.start_register)
        button_row.addWidget(self.register_start_button)

        self.run_bot_button = QPushButton("Chay Bot")
        self.run_bot_button.clicked.connect(self.start_run_bot)
        button_row.addWidget(self.run_bot_button)

        self.stop_button = QPushButton("Dung")
        self.stop_button.clicked.connect(self.stop_process)
        self.stop_button.setEnabled(False)
        button_row.addWidget(self.stop_button)
        button_row.addStretch()

        self.pending_bank_label = QLabel("Tai khoan chua co bank: 0")
        layout.addWidget(self.pending_bank_label)

        layout.addStretch()

    def create_secret_row(self, field_name):
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)

        input_field = QLineEdit()
        input_field.setObjectName(field_name)
        input_field.setEchoMode(QLineEdit.Password)
        row.addWidget(input_field)

        eye_button = QPushButton("👁")
        eye_button.setFixedWidth(36)
        eye_button.setCheckable(True)
        eye_button.clicked.connect(lambda checked, field=input_field: self.toggle_secret_visibility(field, checked))
        row.addWidget(eye_button)
        return input_field, wrapper

    def toggle_secret_visibility(self, field, is_visible):
        field.setEchoMode(QLineEdit.Normal if is_visible else QLineEdit.Password)

    def load_runtime_config_into_ui(self):
        self.capmonster_input.setText(getattr(config, "CAPMONSTER_API_KEY", ""))
        self.telegram_token_input.setText(getattr(config, "TELEGRAM_BOT_TOKEN", ""))
        self.telegram_chat_id_input.setText(getattr(config, "TELEGRAM_CHAT_ID", ""))

    def on_apply_config_clicked(self):
        self.apply_runtime_config(log_result=True)

    def apply_runtime_config(self, log_result=True):
        capmonster_key = self.capmonster_input.text().strip()
        telegram_token = self.telegram_token_input.text().strip()
        telegram_chat_id = self.telegram_chat_id_input.text().strip()

        config.CAPMONSTER_API_KEY = capmonster_key
        config.TELEGRAM_BOT_TOKEN = telegram_token
        config.TELEGRAM_CHAT_ID = telegram_chat_id

        register.CAPMONSTER_API_KEY = capmonster_key
        telegram_bot.TELEGRAM_BOT_TOKEN = telegram_token
        telegram_bot.TELEGRAM_CHAT_ID = telegram_chat_id

        self.telegram = TelegramNotifier(bot_token=telegram_token, chat_id=telegram_chat_id)

        if log_result:
            self.log("Da ap dung cau hinh CapMonster va Telegram tu giao dien", "SUCCESS")

    def setup_accounts_tab(self):
        layout = QVBoxLayout(self.accounts_tab)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)

        self.load_accounts_button = QPushButton("Tai file")
        self.load_accounts_button.clicked.connect(self.load_accounts_from_file_dialog)
        button_row.addWidget(self.load_accounts_button)

        self.save_accounts_button = QPushButton("Luu file")
        self.save_accounts_button.clicked.connect(self.save_accounts_to_file)
        button_row.addWidget(self.save_accounts_button)

        self.clear_accounts_button = QPushButton("Xoa tat ca")
        self.clear_accounts_button.clicked.connect(self.clear_all_accounts)
        button_row.addWidget(self.clear_accounts_button)
        button_row.addStretch()

        self.accounts_table = QTableWidget(0, 7)
        self.accounts_table.setHorizontalHeaderLabels(
            ["STT", "Username", "Password", "Phone", "Bank Account", "Bank Name", "Owner"]
        )
        self.accounts_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.accounts_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.accounts_table)

    def setup_log_tab(self):
        layout = QVBoxLayout(self.log_tab)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)
        clear_button = QPushButton("Xoa log")
        clear_button.clicked.connect(self.log_text.clear)
        button_row.addWidget(clear_button)
        button_row.addStretch()

    def log(self, message, level="INFO", thread_id=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        thread_text = f"[T{thread_id}] " if thread_id else ""
        self.log_queue.put((timestamp, thread_text, message, level.upper()))

    def process_queues(self):
        while True:
            try:
                timestamp, thread_text, message, level = self.log_queue.get_nowait()
            except queue.Empty:
                break
            line = f"[{timestamp}] {thread_text}{message}"
            self.log_text.append(line)

        while True:
            try:
                command, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if command == "refresh_accounts":
                self.update_accounts_display()
            elif command == "refresh_pending":
                self.update_pending_bank_count()
            elif command == "set_running":
                self.apply_running_state(payload["running"], payload.get("mode"))
            elif command == "finish_run":
                self.finish_process(payload.get("message"), payload.get("level", "INFO"))
            elif command == "proxy_count":
                self.proxy_count_label.setText(f"Proxy san sang: {payload['count']}")

    def queue_ui(self, command, payload=None):
        self.ui_queue.put((command, payload or {}))

    def apply_running_state(self, running, mode=None):
        self.is_running = running
        if running:
            self.current_mode = mode
        self.register_start_button.setEnabled(not running)
        self.run_bot_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.apply_config_button.setEnabled(not running)

    def finish_process(self, message=None, level="INFO"):
        self.is_running = False
        self.stop_flag = True
        self.current_mode = None
        self.register_start_button.setEnabled(True)
        self.run_bot_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.apply_config_button.setEnabled(True)
        if message:
            self.log(message, level)

    def set_table_item(self, table, row, column, value):
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(Qt.AlignCenter if column == 0 else Qt.AlignLeft | Qt.AlignVCenter)
        table.setItem(row, column, item)

    def load_accounts_from_file(self, filename="accounts.txt"):
        if not os.path.exists(filename):
            with self.accounts_lock:
                self.accounts_list = []
            self.update_accounts_display()
            self.update_pending_bank_count()
            return

        accounts = []
        bank_data = self.load_bank_data()
        bank_data_changed = False
        try:
            with open(filename, "r", encoding="utf-8") as file:
                for raw_line in file:
                    line = raw_line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    account = {
                        "username": parts[0] if len(parts) > 0 else "",
                        "password": parts[1] if len(parts) > 1 else "",
                        "phone": parts[2] if len(parts) > 2 else "",
                        "bank_account_no": "",
                        "bank_name": "",
                        "bank_account_name": "",
                    }
                    account_key = self.build_account_key(account)
                    saved_bank = bank_data.get(account_key, {})
                    legacy_bank = {
                        "bank_account_no": parts[3] if len(parts) > 3 else "",
                        "bank_name": parts[4] if len(parts) > 4 else "",
                        "bank_account_name": parts[5] if len(parts) > 5 else "",
                    }

                    if legacy_bank["bank_account_no"]:
                        account.update(legacy_bank)
                        bank_data[account_key] = legacy_bank
                        bank_data_changed = True
                    elif saved_bank.get("bank_account_no"):
                        account.update(
                            {
                                "bank_account_no": saved_bank.get("bank_account_no", ""),
                                "bank_name": saved_bank.get("bank_name", ""),
                                "bank_account_name": saved_bank.get("bank_account_name", ""),
                            }
                        )

                    accounts.append(account)
            with self.accounts_lock:
                self.accounts_list = accounts
            if bank_data_changed:
                self.save_bank_data(bank_data)
            self.log(f"Da tai {len(accounts)} tai khoan tu {filename}", "SUCCESS")
            self.update_accounts_display()
            self.update_pending_bank_count()
        except Exception as error:
            self.log(f"Loi tai file: {error}", "ERROR")

    def load_accounts_from_file_dialog(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Chon file tai khoan", "", "Text Files (*.txt)")
        if filename:
            self.load_accounts_from_file(filename)

    def save_accounts_to_file(self, filename="accounts.txt"):
        try:
            with self.accounts_lock:
                snapshot = [dict(account) for account in self.accounts_list]
            with open(filename, "w", encoding="utf-8") as file:
                for account in snapshot:
                    line = f"{account.get('username', '')}|{account.get('password', '')}|{account.get('phone', '')}\n"
                    file.write(line)
            self.log(f"Da luu {len(snapshot)} tai khoan vao {filename}", "SUCCESS")
        except Exception as error:
            self.log(f"Loi luu file: {error}", "ERROR")

    def clear_all_accounts(self):
        reply = QMessageBox.question(self, "Xac nhan", "Xoa tat ca tai khoan?")
        if reply != QMessageBox.Yes:
            return
        with self.accounts_lock:
            self.accounts_list = []
        self.save_bank_data({})
        self.save_accounts_to_file()
        self.update_accounts_display()
        self.update_pending_bank_count()

    def update_accounts_display(self):
        with self.accounts_lock:
            snapshot = [dict(account) for account in self.accounts_list]
        self.accounts_table.setRowCount(len(snapshot))
        for index, account in enumerate(snapshot, start=1):
            values = [
                index,
                account.get("username", ""),
                account.get("password", ""),
                account.get("phone", ""),
                account.get("bank_account_no", ""),
                account.get("bank_name", ""),
                account.get("bank_account_name", ""),
            ]
            for column, value in enumerate(values):
                self.set_table_item(self.accounts_table, index - 1, column, value)

    def update_pending_bank_count(self):
        with self.accounts_lock:
            pending_count = sum(1 for account in self.accounts_list if not account.get("bank_account_no"))
        self.pending_bank_label.setText(f"Tai khoan chua co bank: {pending_count}")
        self.log(f"Co {pending_count} tai khoan chua co thong tin ngan hang", "INFO")

    def reload_proxies(self):
        self.proxy_manager = ProxyManager()
        self.proxy_count_label.setText(f"Proxy san sang: {self.proxy_manager.get_proxy_count()}")
        self.log(f"Da tai lai {self.proxy_manager.get_proxy_count()} proxy", "SUCCESS")

    def start_background(self, mode, target):
        if self.is_running:
            return
        self.apply_runtime_config(log_result=False)
        self.stop_flag = False
        self.queue_ui("set_running", {"running": True, "mode": mode})
        self.process_thread = threading.Thread(target=target, daemon=True)
        self.process_thread.start()

    def start_register(self):
        self.start_background("register", self.process_register)

    def start_run_bot(self):
        self.start_background("run_bot", self.process_run_bot)

    def process_register(self):
        total = self.register_count_spin.value()
        max_threads = self.register_threads_spin.value()
        use_proxy = self.register_use_proxy_check.isChecked()
        auto_save = self.register_save_file_check.isChecked()

        success_count = 0
        failure_count = 0
        attempt_count = 0
        counters_lock = threading.Lock()
        save_lock = threading.Lock()
        stop_event = threading.Event()

        def worker(thread_id):
            nonlocal success_count, failure_count, attempt_count
            while not self.stop_flag and not stop_event.is_set():
                with counters_lock:
                    if success_count >= total:
                        stop_event.set()
                        return
                    attempt_count += 1
                    current_attempt = attempt_count
                    remaining = total - success_count

                proxy = None
                if use_proxy:
                    proxy = self.proxy_manager.get_proxy()
                    if not proxy:
                        self.log("Khong con proxy kha dung, dung dang ky", "ERROR", thread_id)
                        stop_event.set()
                        return

                self.log(
                    f"Thu dang ky lan {current_attempt}, con thieu {remaining} tai khoan thanh cong",
                    "INFO",
                    thread_id,
                )

                creator = AccountCreator(proxy=proxy)
                account, error = creator.register_only(callback=lambda msg: self.log(msg, "INFO", thread_id))

                if account:
                    with counters_lock:
                        if success_count >= total:
                            stop_event.set()
                            return
                        success_count += 1
                        current_success = success_count
                    with self.accounts_lock:
                        self.accounts_list.append(account)
                    self.log(f"Da dang ky: {account['username']} ({current_success}/{total})", "SUCCESS", thread_id)
                    if auto_save:
                        with save_lock:
                            self.save_accounts_to_file()
                    self.queue_ui("refresh_accounts")
                    self.queue_ui("refresh_pending")
                    if current_success >= total:
                        stop_event.set()
                else:
                    with counters_lock:
                        failure_count += 1
                    self.log(f"Dang ky that bai: {error}", "ERROR", thread_id)
                    if proxy and ("proxy" in str(error).lower() or "timeout" in str(error).lower()):
                        self.proxy_manager.mark_proxy_failed(proxy)
                        self.queue_ui("proxy_count", {"count": self.proxy_manager.get_proxy_count()})
                        self.log(f"Da loai proxy loi: {proxy}", "WARNING", thread_id)
                    time.sleep(1)

        self.log(f"Bat dau dang ky muc tieu {total} tai khoan voi {max_threads} luong", "SUCCESS")
        threads = [threading.Thread(target=worker, args=(index + 1,), daemon=True) for index in range(max_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        level = "SUCCESS" if success_count >= total else "WARNING"
        self.queue_ui(
            "finish_run",
            {
                "message": (
                    f"Ket thuc dang ky: Thanh cong {success_count}/{total} | "
                    f"That bai {failure_count} | Tong luot thu {attempt_count}"
                ),
                "level": level,
            },
        )

    def get_pending_accounts_snapshot(self):
        with self.accounts_lock:
            return [account for account in self.accounts_list if not account.get("bank_account_no")]

    def process_run_bot(self):
        self.log("Chay bot: nap lai danh sach tai khoan tu accounts.txt", "INFO")
        self.load_accounts_from_file()

        max_threads = self.bank_threads_spin.value()
        amount = self.bank_amount_spin.value()
        retry_limit = self.bank_retry_spin.value()
        use_proxy = self.bank_use_proxy_check.isChecked()
        send_telegram = self.bank_send_telegram_check.isChecked()

        pending_accounts = self.get_pending_accounts_snapshot()
        if not pending_accounts:
            self.queue_ui("finish_run", {"message": "Khong co tai khoan nao can lay bank", "level": "WARNING"})
            return

        self.log(
            f"Bat dau lay bank cho {len(pending_accounts)} tai khoan voi {max_threads} luong, retry {retry_limit}",
            "SUCCESS",
        )

        success_count = 0
        failed_count = 0
        counters_lock = threading.Lock()
        save_lock = threading.Lock()
        task_queue = queue.Queue()

        for account in pending_accounts:
            task_queue.put(account)

        def worker(thread_id):
            nonlocal success_count, failed_count
            while not self.stop_flag:
                try:
                    account = task_queue.get(timeout=1)
                except queue.Empty:
                    return

                username = account.get("username", "")
                success = False
                last_error = "Unknown error"

                for attempt in range(1, 2):
                    if self.stop_flag:
                        return

                    proxy = None
                    if use_proxy:
                        proxy = self.proxy_manager.get_proxy()
                        if not proxy:
                            last_error = "Khong con proxy kha dung"
                            break

                    self.log(
                        f"{username}: dang dang nhap va chay chuoi 6 request",
                        "INFO",
                        thread_id,
                    )

                    fetcher = BankFetcher(proxy=proxy)
                    success, result = fetcher.fetch_bank_for_account(
                        account,
                        amount,
                        callback=lambda msg: self.log(msg, "INFO", thread_id),
                    )

                    if success:
                        result_items = result.get("results") or [result]
                        final_result = result_items[-1]
                        with self.accounts_lock:
                            account["bank_account_no"] = final_result["bank_account_no"]
                            account["bank_name"] = final_result["bank_name"]
                            account["bank_account_name"] = final_result["bank_account_name"]
                        with counters_lock:
                            success_count += 1
                        for item in result_items:
                            self.log(f"{username}: {item['formatted']}", "SUCCESS", thread_id)
                        if send_telegram:
                            for item in result_items:
                                self.telegram.send_bank_info_only(item)
                        with save_lock:
                            self.save_bank_info_for_account(account)
                            self.save_accounts_to_file()
                        self.queue_ui("refresh_accounts")
                        self.queue_ui("refresh_pending")
                        break

                    last_error = str(result)
                    self.log(f"{username}: lay bank that bai lan {attempt} - {last_error}", "ERROR", thread_id)

                    if proxy and ("proxy" in last_error.lower() or "timeout" in last_error.lower()):
                        self.proxy_manager.mark_proxy_failed(proxy)
                        self.queue_ui("proxy_count", {"count": self.proxy_manager.get_proxy_count()})
                        self.log(f"Da loai proxy loi: {proxy}", "WARNING", thread_id)

                    break

                if not success:
                    with counters_lock:
                        failed_count += 1
                    self.log(f"{username}: bo qua tai khoan nay, loi cuoi {last_error}", "WARNING", thread_id)

        threads = [
            threading.Thread(target=worker, args=(index + 1,), daemon=True)
            for index in range(min(max_threads, len(pending_accounts)))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        level = "SUCCESS" if failed_count == 0 else "WARNING"
        self.queue_ui(
            "finish_run",
            {
                "message": (
                    f"Ket thuc lay bank: Thanh cong {success_count}/{len(pending_accounts)} | "
                    f"That bai {failed_count}"
                ),
                "level": level,
            },
        )

    def stop_process(self):
        if not self.is_running:
            return
        self.stop_flag = True
        self.finish_process("Da dung qua trinh", "WARNING")

    def closeEvent(self, event):
        if self.is_running:
            reply = QMessageBox.question(self, "Thoat", "Bot dang chay, ban co chac muon thoat?")
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.stop_flag = True
        event.accept()


if __name__ == "__main__":
    app = QApplication([])
    window = RegGameWindow()
    window.show()
    app.exec()
