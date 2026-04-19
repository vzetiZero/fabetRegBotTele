import json
import os
import queue
import random
import threading
import time
from datetime import datetime

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
    QProgressBar,
)

import config
from account_creator import AccountCreator
from bank_fetcher import BankFetcher
from proxy_manager import ProxyManager
from proxy_rotator import ProxyRotator
from rate_limiter import AccountRateLimiter
from telegram_bot import TelegramNotifier


class RegGameWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RegGame Bot - Tạo tài khoản tự động")
        self.resize(1400, 900)

        # Khởi tạo các thành phần
        self.proxy_manager = ProxyManager()
        self.proxy_rotator = ProxyRotator(self.proxy_manager, min_delay_between_requests=3)
        self.telegram = TelegramNotifier()
        self.rate_limiter = AccountRateLimiter(accounts_per_window=3, time_window=30)
        
        # Dữ liệu
        self.bank_data_file = os.path.join("data", "bank_accounts.json")
        self.accounts_list = []
        self.accounts_lock = threading.Lock()
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()

        # Trạng thái
        self.is_running = False
        self.stop_flag = False
        self.current_mode = None
        self.process_thread = None
        self.worker_threads = []
        self.stop_event = threading.Event()

        # Setup UI
        self.setup_ui()
        self.apply_theme()
        self.load_runtime_config_into_ui()
        self.apply_runtime_config(log_result=False)
        self.load_accounts_from_file()

        # Timer xử lý queue
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queues)
        self.timer.start(100)
        
        # Timer cập nhật trạng thái
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status_display)
        self.status_timer.start(1000)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.register_tab = QWidget()
        self.accounts_tab = QWidget()
        self.log_tab = QWidget()
        self.stats_tab = QWidget()

        self.tabs.addTab(self.register_tab, "📝 Đăng Ký")
        self.tabs.addTab(self.accounts_tab, "👥 Tài Khoản")
        self.tabs.addTab(self.stats_tab, "📊 Thống Kê")
        self.tabs.addTab(self.log_tab, "📋 Log")

        self.setup_register_tab()
        self.setup_accounts_tab()
        self.setup_stats_tab()
        self.setup_log_tab()

    def apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #0b0b0b;
                color: #f5f5f5;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QTabWidget::pane {
                border: 1px solid #2a2a2a;
                background: #101010;
                border-radius: 12px;
                top: -1px;
            }
            QTabBar::tab {
                background: #141414;
                color: #a8a8a8;
                padding: 10px 18px;
                margin-right: 6px;
                border: 1px solid #2a2a2a;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
            QTabBar::tab:selected {
                background: #f5f5f5;
                color: #0b0b0b;
            }
            QGroupBox {
                background: #121212;
                border: 1px solid #2a2a2a;
                border-radius: 14px;
                margin-top: 14px;
                padding-top: 14px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                color: #ffffff;
            }
            QLabel {
                color: #f2f2f2;
            }
            QLineEdit, QSpinBox, QTextEdit, QTableWidget {
                background: #050505;
                color: #ffffff;
                border: 1px solid #303030;
                border-radius: 10px;
                padding: 8px;
                selection-background-color: #ffffff;
                selection-color: #000000;
            }
            QHeaderView::section {
                background: #171717;
                color: #f5f5f5;
                border: none;
                border-bottom: 1px solid #2f2f2f;
                padding: 10px;
            }
            QPushButton {
                background: #f5f5f5;
                color: #050505;
                border: 1px solid #f5f5f5;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #d9d9d9;
            }
            QPushButton:disabled {
                background: #1a1a1a;
                color: #666666;
                border-color: #2b2b2b;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid #5a5a5a;
                background: #101010;
            }
            QCheckBox::indicator:checked {
                background: #ffffff;
                border-color: #ffffff;
            }
            QProgressBar {
                background: #151515;
                color: #ffffff;
                border: 1px solid #2a2a2a;
                border-radius: 8px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #ffffff;
                border-radius: 7px;
            }
            """
        )

    def interruptible_sleep(self, seconds):
        return self.stop_event.wait(seconds)

    def join_active_threads(self, include_process_thread=True, timeout=2.0):
        current = threading.current_thread()
        for thread in list(self.worker_threads):
            if thread and thread.is_alive() and thread is not current:
                thread.join(timeout=timeout)
        self.worker_threads = [thread for thread in self.worker_threads if thread and thread.is_alive()]

        if (
            include_process_thread
            and self.process_thread
            and self.process_thread.is_alive()
            and self.process_thread is not current
        ):
            self.process_thread.join(timeout=timeout)

    def setup_register_tab(self):
        layout = QVBoxLayout(self.register_tab)

        # ========== Cấu hình chạy ==========
        config_box = QGroupBox("⚙️ Cấu Hình Chạy")
        config_layout = QGridLayout(config_box)
        layout.addWidget(config_box)

        # Hàng 0
        config_layout.addWidget(QLabel("📊 Số lượng tài khoản:"), 0, 0)
        self.register_count_spin = QSpinBox()
        self.register_count_spin.setRange(1, 10000)
        self.register_count_spin.setValue(10)
        self.register_count_spin.setToolTip("Tổng số tài khoản cần tạo")
        config_layout.addWidget(self.register_count_spin, 0, 1)

        config_layout.addWidget(QLabel("🔧 Số luồng đăng ký:"), 0, 2)
        self.register_threads_spin = QSpinBox()
        self.register_threads_spin.setRange(1, 5)
        self.register_threads_spin.setValue(1)
        self.register_threads_spin.setToolTip("Chỉ nên dùng 1 luồng để tránh bị chặn")
        config_layout.addWidget(self.register_threads_spin, 0, 3)

        # Hàng 1
        config_layout.addWidget(QLabel("🔁 Số lần thử lại:"), 1, 0)
        self.register_retry_spin = QSpinBox()
        self.register_retry_spin.setRange(1, 5)
        self.register_retry_spin.setValue(2)
        config_layout.addWidget(self.register_retry_spin, 1, 1)

        config_layout.addWidget(QLabel("💵 Số tiền mặc định:"), 1, 2)
        self.default_amount_spin = QSpinBox()
        self.default_amount_spin.setRange(1000, 100000000)
        self.default_amount_spin.setSingleStep(1000)
        self.default_amount_spin.setValue(300000)
        config_layout.addWidget(self.default_amount_spin, 1, 3)

        # Hàng 2
        self.register_use_proxy_check = QCheckBox("🌐 Sử dụng proxy khi đăng ký")
        self.register_use_proxy_check.setChecked(True)
        config_layout.addWidget(self.register_use_proxy_check, 2, 0, 1, 2)

        self.register_save_file_check = QCheckBox("💾 Tự động lưu file")
        self.register_save_file_check.setChecked(True)
        config_layout.addWidget(self.register_save_file_check, 2, 2, 1, 2)

        # ========== Cấu hình Bank ==========
        bank_box = QGroupBox("🏦 Cấu Hình Lấy Bank")
        bank_layout = QGridLayout(bank_box)
        layout.addWidget(bank_box)

        # Hàng 0
        bank_layout.addWidget(QLabel("🔧 Số luồng lấy bank:"), 0, 0)
        self.bank_threads_spin = QSpinBox()
        self.bank_threads_spin.setRange(1, 10)
        self.bank_threads_spin.setValue(3)
        bank_layout.addWidget(self.bank_threads_spin, 0, 1)

        bank_layout.addWidget(QLabel("💵 Số tiền nap:"), 0, 2)
        self.bank_amount_spin = QSpinBox()
        self.bank_amount_spin.setRange(1000, 100000000)
        self.bank_amount_spin.setSingleStep(1000)
        self.bank_amount_spin.setValue(300000)
        bank_layout.addWidget(self.bank_amount_spin, 0, 3)

        # Hàng 1
        bank_layout.addWidget(QLabel("🔄 Retry mỗi tài khoản:"), 1, 0)
        self.bank_retry_spin = QSpinBox()
        self.bank_retry_spin.setRange(1, 10)
        self.bank_retry_spin.setValue(3)
        bank_layout.addWidget(self.bank_retry_spin, 1, 1)

        self.bank_use_proxy_check = QCheckBox("🌐 Sử dụng proxy khi lấy bank")
        self.bank_use_proxy_check.setChecked(True)
        bank_layout.addWidget(self.bank_use_proxy_check, 1, 2, 1, 2)

        # Hàng 2
        self.bank_send_telegram_check = QCheckBox("📨 Gửi Telegram khi có bank mới")
        self.bank_send_telegram_check.setChecked(True)
        bank_layout.addWidget(self.bank_send_telegram_check, 2, 0, 1, 3)

        # ========== Cấu hình bảo mật ==========
        secret_box = QGroupBox("🔐 Cấu Hình Bảo Mật")
        secret_layout = QFormLayout(secret_box)
        layout.addWidget(secret_box)

        self.capmonster_input, capmonster_row = self.create_secret_row("CAPMONSTER_API_KEY")
        secret_layout.addRow("CapMonster API Key:", capmonster_row)

        self.telegram_token_input, token_row = self.create_secret_row("TELEGRAM_BOT_TOKEN")
        secret_layout.addRow("Telegram Bot Token:", token_row)

        self.telegram_chat_id_input, chat_row = self.create_secret_row("TELEGRAM_CHAT_ID")
        secret_layout.addRow("Telegram Chat ID:", chat_row)

        # ========== Panel thông tin ==========
        info_panel = QGroupBox("📊 Trạng Thái Hệ Thống")
        info_layout = QGridLayout(info_panel)
        layout.addWidget(info_panel)

        # Proxy status
        self.proxy_status_label = QLabel("🌐 Proxy: Đang tải...")
        self.proxy_status_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 5px; border-radius: 3px; }")
        info_layout.addWidget(self.proxy_status_label, 0, 0, 1, 2)

        # Rate limit status
        self.rate_limit_label = QLabel("⏱️ Giới hạn: 3 tk/30s | Slot trống: 3 | Đã tạo: 0")
        self.rate_limit_label.setStyleSheet("QLabel { background-color: #e8f4f8; padding: 5px; border-radius: 3px; }")
        info_layout.addWidget(self.rate_limit_label, 0, 2, 1, 2)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        info_layout.addWidget(self.progress_bar, 1, 0, 1, 4)

        # Pending bank count
        self.pending_bank_label = QLabel("🏦 Tài khoản chưa có bank: 0")
        info_layout.addWidget(self.pending_bank_label, 2, 0, 1, 2)

        # ========== Button controls ==========
        button_panel = QHBoxLayout()
        layout.addLayout(button_panel)

        self.apply_config_button = QPushButton("💾 Áp dụng cấu hình")
        self.apply_config_button.clicked.connect(self.on_apply_config_clicked)
        button_panel.addWidget(self.apply_config_button)

        self.reload_proxy_button = QPushButton("🔄 Tải lại proxy")
        self.reload_proxy_button.clicked.connect(self.reload_proxies)
        button_panel.addWidget(self.reload_proxy_button)

        button_panel.addStretch()

        self.register_start_button = QPushButton("🚀 Bắt đầu đăng ký")
        self.register_start_button.clicked.connect(self.start_register)
        self.register_start_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        button_panel.addWidget(self.register_start_button)

        self.run_bot_button = QPushButton("🤖 Chạy Bot lấy bank")
        self.run_bot_button.clicked.connect(self.start_run_bot)
        self.run_bot_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
        """)
        button_panel.addWidget(self.run_bot_button)

        self.stop_button = QPushButton("⛔ Dừng")
        self.stop_button.clicked.connect(self.stop_process)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        button_panel.addWidget(self.stop_button)

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

    def setup_accounts_tab(self):
        layout = QVBoxLayout(self.accounts_tab)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)

        self.load_accounts_button = QPushButton("📂 Tải file")
        self.load_accounts_button.clicked.connect(self.load_accounts_from_file_dialog)
        button_row.addWidget(self.load_accounts_button)

        self.save_accounts_button = QPushButton("💾 Lưu file")
        self.save_accounts_button.clicked.connect(self.save_accounts_to_file)
        button_row.addWidget(self.save_accounts_button)

        self.clear_accounts_button = QPushButton("🗑️ Xóa tất cả")
        self.clear_accounts_button.clicked.connect(self.clear_all_accounts)
        button_row.addWidget(self.clear_accounts_button)
        
        self.export_bank_button = QPushButton("📤 Xuất bank")
        self.export_bank_button.clicked.connect(self.export_bank_info)
        button_row.addWidget(self.export_bank_button)
        
        button_row.addStretch()

        self.accounts_table = QTableWidget(0, 8)
        self.accounts_table.setHorizontalHeaderLabels(
            ["STT", "Username", "Password", "Phone", "Bank Account", "Bank Name", "Owner", "Proxy"]
        )
        self.accounts_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.accounts_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.accounts_table)

    def setup_stats_tab(self):
        layout = QVBoxLayout(self.stats_tab)
        
        # Thống kê tổng quan
        stats_box = QGroupBox("📈 Thống Kê Tổng Quan")
        stats_layout = QGridLayout(stats_box)
        layout.addWidget(stats_box)
        
        self.total_accounts_label = QLabel("Tổng số tài khoản: 0")
        stats_layout.addWidget(self.total_accounts_label, 0, 0)
        
        self.total_bank_label = QLabel("Số tài khoản có bank: 0")
        stats_layout.addWidget(self.total_bank_label, 0, 1)
        
        self.success_rate_label = QLabel("Tỷ lệ thành công: 0%")
        stats_layout.addWidget(self.success_rate_label, 1, 0)
        
        self.proxy_stats_label = QLabel("Proxy đã dùng: 0")
        stats_layout.addWidget(self.proxy_stats_label, 1, 1)
        
        # Thống kê rate limit
        rate_box = QGroupBox("⏱️ Rate Limit Status")
        rate_layout = QGridLayout(rate_box)
        layout.addWidget(rate_box)
        
        self.rate_detail_label = QLabel("Chi tiết rate limit")
        rate_layout.addWidget(self.rate_detail_label, 0, 0, 1, 2)
        
        layout.addStretch()

    def setup_log_tab(self):
        layout = QVBoxLayout(self.log_tab)
        
        # Filter buttons
        filter_row = QHBoxLayout()
        layout.addLayout(filter_row)
        
        self.filter_all_btn = QPushButton("Tất cả")
        self.filter_all_btn.clicked.connect(lambda: self.set_log_filter("ALL"))
        filter_row.addWidget(self.filter_all_btn)
        
        self.filter_success_btn = QPushButton("Thành công")
        self.filter_success_btn.clicked.connect(lambda: self.set_log_filter("SUCCESS"))
        filter_row.addWidget(self.filter_success_btn)
        
        self.filter_error_btn = QPushButton("Lỗi")
        self.filter_error_btn.clicked.connect(lambda: self.set_log_filter("ERROR"))
        filter_row.addWidget(self.filter_error_btn)
        
        self.filter_warning_btn = QPushButton("Cảnh báo")
        self.filter_warning_btn.clicked.connect(lambda: self.set_log_filter("WARNING"))
        filter_row.addWidget(self.filter_warning_btn)
        
        filter_row.addStretch()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.clear_log_button = QPushButton("🗑️ Xóa log")
        self.clear_log_button.clicked.connect(self.log_text.clear)
        filter_row.addWidget(self.clear_log_button)
        
        self.log_filter = "ALL"
        self.all_logs = []

    def set_log_filter(self, filter_type):
        self.log_filter = filter_type
        self.refresh_log_display()

    def refresh_log_display(self):
        self.log_text.clear()
        for log in self.all_logs:
            if self.log_filter == "ALL" or self.log_filter in log:
                self.log_text.append(log)

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

        self.telegram = TelegramNotifier(bot_token=telegram_token, chat_id=telegram_chat_id)

        if log_result:
            self.log("✅ Đã áp dụng cấu hình CapMonster và Telegram", "SUCCESS")

    def log(self, message, level="INFO", thread_id=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        thread_text = f"[T{thread_id}] " if thread_id else ""
        log_line = f"[{timestamp}] {thread_text}[{level}] {message}"
        
        self.all_logs.append(log_line)
        if self.log_filter == "ALL" or level in self.log_filter:
            self.log_text.append(log_line)
        
        # Giới hạn số lượng log
        if len(self.all_logs) > 1000:
            self.all_logs = self.all_logs[-500:]

    def process_queues(self):
        while True:
            try:
                timestamp, thread_text, message, level = self.log_queue.get_nowait()
            except queue.Empty:
                break
            line = f"[{timestamp}] {thread_text}{message}"
            self.all_logs.append(line)
            if self.log_filter == "ALL" or level in self.log_filter:
                self.log_text.append(line)

        while True:
            try:
                command, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if command == "refresh_accounts":
                self.update_accounts_display()
                self.update_stats_display()
            elif command == "refresh_pending":
                self.update_pending_bank_count()
            elif command == "set_running":
                self.apply_running_state(payload["running"], payload.get("mode"))
            elif command == "finish_run":
                self.finish_process(payload.get("message"), payload.get("level", "INFO"))
            elif command == "proxy_count":
                self.proxy_status_label.setText(f"🌐 Proxy: {payload['count']} proxy sẵn sàng")
            elif command == "update_rate_limit":
                self.update_rate_limit_status()
            elif command == "update_progress":
                self.update_progress(payload["current"], payload["total"])
            elif command == "show_progress":
                self.progress_bar.setVisible(payload.get("show", True))

    def update_status_display(self):
        """Cập nhật hiển thị trạng thái định kỳ"""
        if self.is_running:
            status = self.rate_limiter.get_status()
            self.rate_limit_label.setText(
                f"⏱️ Giới hạn: {status['max_per_window']} tk/{status['time_window']}s | "
                f"Slot trống: {status['remaining_slots']} | "
                f"Đã tạo: {status['total_created']} | "
                f"Lỗi: {status['total_failed']}"
            )
        
        # Cập nhật proxy stats
        if self.proxy_rotator:
            stats = self.proxy_rotator.get_stats()
            self.proxy_stats_label.setText(f"Proxy đã dùng: {stats['used_proxies_count']}")

    def update_rate_limit_status(self):
        status = self.rate_limiter.get_status()
        self.rate_limit_label.setText(
            f"⏱️ Giới hạn: {status['max_per_window']} tk/{status['time_window']}s | "
            f"Slot trống: {status['remaining_slots']} | "
            f"Đã tạo: {status['total_created']} | "
            f"Lỗi: {status['total_failed']}"
        )
        
        # Cập nhật chi tiết trong stats tab
        rate_detail = (
            f"📊 Rate Limit Chi Tiết:\n"
            f"  • Số lượng tối đa: {status['max_per_window']} tài khoản\n"
            f"  • Thời gian cửa sổ: {status['time_window']} giây\n"
            f"  • Slot còn trống: {status['remaining_slots']}\n"
            f"  • Thời gian chờ: {status['wait_time']:.1f} giây\n"
            f"  • Đã tạo thành công: {status['total_created']}\n"
            f"  • Đã thất bại: {status['total_failed']}\n"
            f"  • Tỷ lệ thành công: {(status['total_created']/(status['total_created']+status['total_failed'])*100):.1f}%" 
            if (status['total_created'] + status['total_failed']) > 0 else "0%"
        )
        self.rate_detail_label.setText(rate_detail)

    def update_progress(self, current, total):
        """Cập nhật progress bar"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        if current >= total:
            self.progress_bar.setVisible(False)

    def update_stats_display(self):
        """Cập nhật thống kê"""
        with self.accounts_lock:
            total = len(self.accounts_list)
            with_bank = sum(1 for acc in self.accounts_list if acc.get("bank_account_no"))
        
        self.total_accounts_label.setText(f"Tổng số tài khoản: {total}")
        self.total_bank_label.setText(f"Số tài khoản có bank: {with_bank}")
        
        if total > 0:
            rate = (with_bank / total) * 100
            self.success_rate_label.setText(f"Tỷ lệ thành công: {rate:.1f}%")

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
        self.reload_proxy_button.setEnabled(not running)

    def finish_process(self, message=None, level="INFO"):
        self.is_running = False
        self.stop_flag = True
        self.current_mode = None
        self.register_start_button.setEnabled(True)
        self.run_bot_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.apply_config_button.setEnabled(True)
        self.reload_proxy_button.setEnabled(True)
        self.progress_bar.setVisible(False)
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
                        "proxy": "",
                        "bank_account_no": "",
                        "bank_name": "",
                        "bank_account_name": "",
                    }
                    account_key = self.build_account_key(account)
                    saved_bank = bank_data.get(account_key, {})
                    account.update(saved_bank)
                    accounts.append(account)
            
            with self.accounts_lock:
                self.accounts_list = accounts
            
            self.log(f"✅ Đã tải {len(accounts)} tài khoản từ {filename}", "SUCCESS")
            self.update_accounts_display()
            self.update_pending_bank_count()
            self.update_stats_display()
        except Exception as error:
            self.log(f"❌ Lỗi tải file: {error}", "ERROR")

    @staticmethod
    def build_account_key(account):
        return "|".join([
            account.get("username", ""),
            account.get("password", ""),
            account.get("phone", ""),
        ])

    def load_bank_data(self):
        if not os.path.exists(self.bank_data_file):
            return {}
        try:
            with open(self.bank_data_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except Exception as error:
            self.log(f"Lỗi tải dữ liệu bank: {error}", "ERROR")
            return {}

    def save_bank_data(self, bank_data):
        try:
            os.makedirs(os.path.dirname(self.bank_data_file), exist_ok=True)
            with open(self.bank_data_file, "w", encoding="utf-8") as file:
                json.dump(bank_data, file, ensure_ascii=False, indent=2)
        except Exception as error:
            self.log(f"Lỗi lưu dữ liệu bank: {error}", "ERROR")

    def save_bank_info_for_account(self, account):
        bank_data = self.load_bank_data()
        bank_data[self.build_account_key(account)] = {
            "bank_account_no": account.get("bank_account_no", ""),
            "bank_name": account.get("bank_name", ""),
            "bank_account_name": account.get("bank_account_name", ""),
        }
        self.save_bank_data(bank_data)

    def load_accounts_from_file_dialog(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Chọn file tài khoản", "", "Text Files (*.txt)")
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
            self.log(f"✅ Đã lưu {len(snapshot)} tài khoản vào {filename}", "SUCCESS")
        except Exception as error:
            self.log(f"❌ Lỗi lưu file: {error}", "ERROR")

    def export_bank_info(self):
        """Xuất thông tin bank ra file"""
        filename, _ = QFileDialog.getSaveFileName(self, "Lưu thông tin bank", "bank_info.txt", "Text Files (*.txt)")
        if filename:
            try:
                with self.accounts_lock:
                    with_bank = [acc for acc in self.accounts_list if acc.get("bank_account_no")]
                
                with open(filename, "w", encoding="utf-8") as file:
                    file.write("Username|Phone|Bank Account|Bank Name|Owner\n")
                    for acc in with_bank:
                        line = f"{acc.get('username')}|{acc.get('phone')}|{acc.get('bank_account_no')}|{acc.get('bank_name')}|{acc.get('bank_account_name')}\n"
                        file.write(line)
                
                self.log(f"✅ Đã xuất {len(with_bank)} thông tin bank ra {filename}", "SUCCESS")
            except Exception as error:
                self.log(f"❌ Lỗi xuất bank: {error}", "ERROR")

    def clear_all_accounts(self):
        reply = QMessageBox.question(self, "Xác nhận", "Bạn có chắc muốn xóa tất cả tài khoản?")
        if reply != QMessageBox.Yes:
            return
        with self.accounts_lock:
            self.accounts_list = []
        self.save_bank_data({})
        self.save_accounts_to_file()
        self.update_accounts_display()
        self.update_pending_bank_count()
        self.update_stats_display()
        self.log("🗑️ Đã xóa tất cả tài khoản", "WARNING")

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
                account.get("proxy", "")[:30],  # Giới hạn độ dài
            ]
            for column, value in enumerate(values):
                self.set_table_item(self.accounts_table, index - 1, column, value)

    def update_pending_bank_count(self):
        with self.accounts_lock:
            pending_count = sum(1 for account in self.accounts_list if not account.get("bank_account_no"))
        self.pending_bank_label.setText(f"🏦 Tài khoản chưa có bank: {pending_count}")

    def reload_proxies(self):
        self.proxy_manager = ProxyManager()
        self.proxy_rotator = ProxyRotator(self.proxy_manager, min_delay_between_requests=3)
        count = self.proxy_manager.get_proxy_count()
        self.proxy_status_label.setText(f"🌐 Proxy: {count} proxy sẵn sàng")
        self.log(f"🔄 Đã tải lại {count} proxy", "SUCCESS")

    def start_background(self, mode, target):
        if self.is_running:
            return
        self.apply_runtime_config(log_result=False)
        self.stop_flag = False
        self.stop_event.clear()
        self.worker_threads = []
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
        max_retries = self.register_retry_spin.value()

        success_count = 0
        failure_count = 0
        counters_lock = threading.Lock()
        save_lock = threading.Lock()

        self.log(f"🚀 BẮT ĐẦU ĐĂNG KÝ {total} TÀI KHOẢN", "SUCCESS")
        self.log(f"📋 Giới hạn: tối đa 3 tài khoản trong 30 giây", "INFO")
        self.log(f"🔄 Mỗi tài khoản dùng 1 proxy riêng, tự động refresh", "INFO")
        self.queue_ui("show_progress", {"show": True})
        self.queue_ui("update_progress", {"current": 0, "total": total})

        def worker(thread_id):
            nonlocal success_count, failure_count
            
            while not self.stop_flag and not self.stop_event.is_set():
                with counters_lock:
                    if success_count >= total:
                        self.stop_event.set()
                        return
                
                # Kiểm tra rate limit
                if not self.rate_limiter.can_create_account():
                    status = self.rate_limiter.get_status()
                    wait_time = status['wait_time']
                    self.log(f"⏳ Đang trong giới hạn, cần chờ {wait_time:.1f} giây...", "WARNING", thread_id)
                    if self.interruptible_sleep(min(wait_time, 5)):
                        return
                    continue
                
                # Lấy proxy mới
                proxy = None
                if use_proxy:
                    proxy = self.proxy_rotator.get_fresh_proxy(force_new=True)
                    if not proxy:
                        self.log("⚠️ Không thể lấy proxy mới, tạm dừng 5s...", "WARNING", thread_id)
                        if self.interruptible_sleep(5):
                            return
                        continue
                
                self.log(f"🔄 Dùng proxy: {proxy if proxy else 'Không dùng proxy'}", "INFO", thread_id)
                
                # Tạo tài khoản
                creator = AccountCreator(proxy=proxy)
                
                def log_callback(msg):
                    self.log(msg, "INFO", thread_id)
                
                start_time = time.time()
                account, error = creator.register_only(
                    amount=self.default_amount_spin.value(),
                    callback=log_callback,
                    max_retries=max_retries
                )
                elapsed = time.time() - start_time
                
                if account:
                    with counters_lock:
                        success_count += 1
                        current_success = success_count
                    
                    account["proxy"] = proxy
                    
                    with self.accounts_lock:
                        self.accounts_list.append(account)
                    
                    self.rate_limiter.record_success()
                    
                    self.log(
                        f"✅ [{current_success}/{total}] THÀNH CÔNG: {account['username']} | "
                        f"Time: {elapsed:.1f}s | Proxy: {proxy}",
                        "SUCCESS", thread_id
                    )
                    
                    if auto_save:
                        with save_lock:
                            self.save_accounts_to_file()
                    
                    self.queue_ui("refresh_accounts")
                    self.queue_ui("refresh_pending")
                    self.queue_ui("update_rate_limit")
                    self.queue_ui("update_progress", {"current": current_success, "total": total})
                    
                    if current_success >= total:
                        self.stop_event.set()
                        
                else:
                    with counters_lock:
                        failure_count += 1
                    
                    self.rate_limiter.record_failure()
                    
                    self.log(f"❌ THẤT BẠI: {error} | Proxy: {proxy}", "ERROR", thread_id)
                    
                    if proxy and ("proxy" in str(error).lower() or "timeout" in str(error).lower()):
                        self.proxy_rotator.mark_proxy_failed(proxy)
                        self.queue_ui("proxy_count", {"count": self.proxy_manager.get_proxy_count()})
                
                # Delay giữa các request
                if self.interruptible_sleep(random.uniform(2, 4)):
                    return
        
        # Chạy threads
        actual_threads = min(max_threads, total)
        threads = []
        for i in range(actual_threads):
            thread = threading.Thread(target=worker, args=(i + 1,), daemon=True)
            thread.start()
            threads.append(thread)
            self.worker_threads.append(thread)
            if self.interruptible_sleep(0.5):
                break
        
        for thread in threads:
            thread.join()
        self.worker_threads = []
        
        # Kết thúc
        status = self.rate_limiter.get_status()
        total_attempts = success_count + failure_count
        success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
        
        level = "SUCCESS" if success_count >= total else "WARNING"
        self.queue_ui(
            "finish_run",
            {
                "message": (
                    f"\n{'='*50}\n"
                    f"📊 KẾT THÚC ĐĂNG KÝ\n"
                    f"{'='*50}\n"
                    f"✅ Thành công: {success_count}/{total}\n"
                    f"❌ Thất bại: {failure_count}\n"
                    f"📈 Tỷ lệ thành công: {success_rate:.1f}%\n"
                    f"⏱️ Thời gian: {status['total_created']} tk trong {status['time_window']}s\n"
                    f"🔄 Tổng lượt thử: {total_attempts}\n"
                    f"{'='*50}"
                ),
                "level": level,
            },
        )

    def get_pending_accounts_snapshot(self):
        with self.accounts_lock:
            return [account for account in self.accounts_list if not account.get("bank_account_no")]

    def process_run_bot(self):
        self.log("🤖 BẮT ĐẦU CHẠY BOT LẤY BANK", "SUCCESS")
        self.log("📋 Đang tải danh sách tài khoản từ accounts.txt...", "INFO")
        self.load_accounts_from_file()

        max_threads = self.bank_threads_spin.value()
        amount = self.bank_amount_spin.value()
        retry_limit = self.bank_retry_spin.value()
        use_proxy = self.bank_use_proxy_check.isChecked()
        send_telegram = self.bank_send_telegram_check.isChecked()

        pending_accounts = self.get_pending_accounts_snapshot()
        if not pending_accounts:
            self.queue_ui("finish_run", {"message": "⚠️ Không có tài khoản nào cần lấy bank", "level": "WARNING"})
            return

        self.log(f"📊 Tìm thấy {len(pending_accounts)} tài khoản chưa có bank", "INFO")
        self.log(f"🔧 Cấu hình: {max_threads} luồng, mỗi tài khoản thử tối đa {retry_limit} lần", "INFO")
        self.log(f"🔄 Mỗi lần thử sẽ dùng proxy MỚI, không dùng lại proxy cũ", "INFO")
        
        self.queue_ui("show_progress", {"show": True})
        self.queue_ui("update_progress", {"current": 0, "total": len(pending_accounts)})

        success_count = 0
        failed_count = 0
        counters_lock = threading.Lock()
        save_lock = threading.Lock()
        task_queue = queue.Queue()

        for account in pending_accounts:
            task_queue.put(account)

        def worker(thread_id):
            nonlocal success_count, failed_count
            
            while not self.stop_flag and not self.stop_event.is_set():
                try:
                    account = task_queue.get(timeout=1)
                except queue.Empty:
                    return

                username = account.get("username", "")
                success = False
                last_error = "Unknown error"
                
                self.log(f"🎯 Bắt đầu xử lý {username}", "INFO", thread_id)
                
                # Thử từng lần với proxy mới
                for attempt in range(1, retry_limit + 1):
                    if self.stop_flag:
                        return
                    
                    self.log(f"{username}: Lần thử {attempt}/{retry_limit}", "INFO", thread_id)
                    
                    # Lấy proxy MỚI cho mỗi lần thử
                    proxy = None
                    if use_proxy:
                        # BẮT BUỘC lấy proxy mới, không dùng proxy cũ
                        proxy = self.proxy_rotator.get_fresh_proxy(force_new=True)
                        if not proxy:
                            self.log(f"{username}: ⚠️ Không thể lấy proxy mới, tạm dừng...", "WARNING", thread_id)
                            if self.interruptible_sleep(3):
                                return
                            continue
                        
                        self.log(f"{username}: 🌐 Dùng proxy mới: {proxy}", "INFO", thread_id)
                    
                    # Tạo fetcher với proxy mới
                    fetcher = BankFetcher(proxy=proxy)
                    
                    # Thử lấy bank
                    fetch_success, result = fetcher.fetch_bank_for_account(
                        account,
                        amount,
                        callback=lambda msg: self.log(msg, "INFO", thread_id),
                    )
                    
                    if fetch_success:
                        # Lấy bank thành công
                        result_items = result.get("results") or [result]
                        final_result = result_items[-1]
                        
                        with self.accounts_lock:
                            account["bank_account_no"] = final_result["bank_account_no"]
                            account["bank_name"] = final_result["bank_name"]
                            account["bank_account_name"] = final_result["bank_account_name"]
                        
                        with counters_lock:
                            success_count += 1
                            current_success = success_count
                        
                        # Log kết quả
                        for item in result_items:
                            self.log(f"✅ {username}: {item['formatted']}", "SUCCESS", thread_id)
                        
                        # Gửi Telegram
                        if send_telegram:
                            for item in result_items:
                                self.telegram.send_bank_info_only(item)
                        
                        # Lưu vào file
                        with save_lock:
                            self.save_bank_info_for_account(account)
                            self.save_accounts_to_file()
                        
                        self.queue_ui("refresh_accounts")
                        self.queue_ui("refresh_pending")
                        self.queue_ui("update_progress", {"current": current_success, "total": len(pending_accounts)})
                        
                        success = True
                        break
                        
                    else:
                        last_error = str(result)
                        self.log(f"❌ {username}: Lần {attempt} thất bại - {last_error}", "ERROR", thread_id)
                        
                        # Đánh dấu proxy lỗi nếu có lỗi proxy
                        if proxy and ("proxy" in last_error.lower() or "timeout" in last_error.lower() or 
                                    "connection" in last_error.lower()):
                            self.proxy_rotator.mark_proxy_failed(proxy)
                            self.log(f"{username}: 🗑️ Đã đánh dấu proxy {proxy} là lỗi", "WARNING", thread_id)
                        
                        # Chờ trước khi thử lại
                        if attempt < retry_limit:
                            wait_time = random.uniform(3, 5)
                            self.log(f"{username}: ⏳ Chờ {wait_time:.1f}s trước lần thử {attempt + 1}...", "INFO", thread_id)
                            if self.interruptible_sleep(wait_time):
                                return
                
                if not success:
                    with counters_lock:
                        failed_count += 1
                    self.log(f"⚠️ {username}: BỎ QUA - Không lấy được bank sau {retry_limit} lần thử với proxy khác nhau", "WARNING", thread_id)
                    self.log(f"   Lỗi cuối: {last_error}", "INFO", thread_id)
            
            self.log(f"🏁 Thread {thread_id} hoàn thành", "INFO", thread_id)
        
        # Chạy threads
        actual_threads = min(max_threads, len(pending_accounts))
        threads = []
        for i in range(actual_threads):
            thread = threading.Thread(target=worker, args=(i + 1,), daemon=True)
            thread.start()
            threads.append(thread)
            self.worker_threads.append(thread)
            if self.interruptible_sleep(0.5):
                break
        
        for thread in threads:
            thread.join()
        self.worker_threads = []
        
        # Kết thúc
        total_processed = success_count + failed_count
        success_rate = (success_count / total_processed * 100) if total_processed > 0 else 0
        
        level = "SUCCESS" if failed_count == 0 else "WARNING"
        self.queue_ui(
            "finish_run",
            {
                "message": (
                    f"\n{'='*50}\n"
                    f"📊 KẾT THÚC LẤY BANK\n"
                    f"{'='*50}\n"
                    f"✅ Thành công: {success_count}/{len(pending_accounts)}\n"
                    f"❌ Thất bại: {failed_count}\n"
                    f"📈 Tỷ lệ thành công: {success_rate:.1f}%\n"
                    f"🔄 Mỗi tài khoản thử tối đa {retry_limit} lần với proxy khác nhau\n"
                    f"{'='*50}"
                ),
                "level": level,
            },
        )
    def stop_process(self):
        if not self.is_running:
            return
        self.stop_flag = True
        self.stop_event.set()
        self.log("Stop requested, waiting for workers to exit...", "WARNING")
        self.join_active_threads(include_process_thread=True, timeout=1.5)
        self.finish_process("All active threads were asked to stop", "WARNING")

    def closeEvent(self, event):
        if self.is_running:
            reply = QMessageBox.question(self, "Thoát", "Bot đang chạy, bạn có chắc muốn thoát?")
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.stop_flag = True
            self.stop_event.set()
            self.join_active_threads(include_process_thread=True, timeout=1.5)
        event.accept()


if __name__ == "__main__":
    app = QApplication([])
    window = RegGameWindow()
    window.show()
    app.exec()
