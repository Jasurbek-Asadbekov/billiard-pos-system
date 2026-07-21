import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QIcon, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QMessageBox, QFileDialog, QScrollArea,
    QSpacerItem, QSizePolicy
)

# =========================================================
# 🔧 O‘ZGARTIRASIZ: APP SOZLAMALARI
# =========================================================
APP_NAME = "Bek Billiard Club"
APP_ICON_ICO = os.path.join("assets", "app.ico")   # 🔧 ikonka
LOGO_PNG = os.path.join("assets", "logo.png")      # 🔧 logo

LOGIN_BG = os.path.join("assets", "login_bg.png")  # 🔧 login fon
MAIN_BG  = os.path.join("assets", "main_bg.png")   # 🔧 bosh ekran fon
TABLE_BG = os.path.join("assets", "table_bg.png")  # 🔧 stol fon

PIN_CODE = "1234"                  # 🔧 O‘ZGARTIRASIZ: PIN
RATE_PER_HOUR = 60000              # 🔧 O‘ZGARTIRASIZ: 1 soat narxi
BILLING_MODE = "proportional"      # "proportional" yoki "ceil_hour"

DB_FILE = "kassa.db"
PRODUCT_IMAGES_DIR = "product_images"


# =========================================================
# DB
# =========================================================
def db_connect():
    return sqlite3.connect(DB_FILE)

def db_init():
    os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)
    with db_connect() as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            size_text TEXT NOT NULL,
            price INTEGER NOT NULL,
            image_path TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            table_no INTEGER NOT NULL,
            seconds INTEGER NOT NULL,
            table_cost INTEGER NOT NULL,
            bar_cost INTEGER NOT NULL,
            total_cost INTEGER NOT NULL,
            payment_method TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            product_price INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id)
        )
        """)
        con.commit()

def db_get_products() -> List[dict]:
    with db_connect() as con:
        cur = con.cursor()
        cur.execute("SELECT id, name, size_text, price, image_path FROM products ORDER BY id DESC")
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "size": r[2], "price": r[3], "image": r[4]} for r in rows]

def db_add_product(name: str, size_text: str, price: int, src_image_path: str) -> None:
    # rasmni project ichiga ko‘chirib saqlaymiz (yo‘qolib qolmasin)
    os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)
    base = os.path.basename(src_image_path)
    safe_name = f"{int(time.time())}_{base}"
    dst = os.path.join(PRODUCT_IMAGES_DIR, safe_name)
    shutil.copy2(src_image_path, dst)

    with db_connect() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO products (name, size_text, price, image_path) VALUES (?, ?, ?, ?)",
            (name.strip(), size_text.strip(), int(price), dst)
        )
        con.commit()

def db_add_receipt(table_no: int, seconds: int, table_cost: int, bar_cost: int, total: int, items: List[dict]) -> int:
    import datetime
    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_connect() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO receipts (created_at, table_no, seconds, table_cost, bar_cost, total_cost, payment_method)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (created_at, table_no, seconds, table_cost, bar_cost, total, "NAQD"))
        rid = cur.lastrowid

        for it in items:
            cur.execute("""
                INSERT INTO receipt_items (receipt_id, product_name, product_price, qty)
                VALUES (?, ?, ?, ?)
            """, (rid, it["name"], it["price"], it["qty"]))

        con.commit()
        return rid


# =========================================================
# HISOB
# =========================================================
def format_sum(amount: int) -> str:
    s = f"{amount:,}".replace(",", " ")
    return f"{s} so'm"

def seconds_to_hms(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def calc_table_cost(elapsed_seconds: int) -> int:
    if elapsed_seconds <= 0:
        return 0
    hours = elapsed_seconds / 3600.0
    if BILLING_MODE == "ceil_hour":
        import math
        return int(math.ceil(hours) * RATE_PER_HOUR)
    return int(round(hours * RATE_PER_HOUR))


# =========================================================
# MODEL: TABLE SESSION
# =========================================================
@dataclass
class TableSession:
    table_no: int
    running: bool = False
    start_ts: float = 0.0
    elapsed_seconds: int = 0
    cart: Dict[int, int] = field(default_factory=dict)  # product_id -> qty

    def start(self):
        if not self.running:
            self.running = True
            self.start_ts = time.time() - self.elapsed_seconds

    def stop(self):
        if self.running:
            self.running = False
            self.elapsed_seconds = int(time.time() - self.start_ts)

    def tick(self):
        if self.running:
            self.elapsed_seconds = int(time.time() - self.start_ts)


# =========================================================
# UI Helpers
# =========================================================
class BackgroundWidget(QWidget):
    """QWidget with scalable background image."""
    def __init__(self, bg_path: str):
        super().__init__()
        self.bg_path = bg_path
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)
        self.bg_label.lower()

    def set_bg(self, path: str):
        self.bg_path = path
        self.update_bg()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_bg()

    def update_bg(self):
        if os.path.exists(self.bg_path):
            pix = QPixmap(self.bg_path)
            if not pix.isNull():
                scaled = pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.bg_label.setPixmap(scaled)
                self.bg_label.setGeometry(0, 0, self.width(), self.height())


def make_logo_button(on_click):
    btn = QPushButton()
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(52, 52)
    btn.setStyleSheet("""
        QPushButton {
            border: none;
            border-radius: 26px;
            background: rgba(255,255,255,0.10);
        }
        QPushButton:hover { background: rgba(255,255,255,0.18); }
    """)
    if os.path.exists(LOGO_PNG):
        pix = QPixmap(LOGO_PNG).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QIcon(pix)
        btn.setIcon(icon)
        btn.setIconSize(QSize(44, 44))
    btn.clicked.connect(on_click)
    return btn


# =========================================================
# LOGIN PAGE
# =========================================================
class LoginPage(BackgroundWidget):
    def __init__(self, on_success):
        super().__init__(LOGIN_BG)
        self.on_success = on_success

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        center = QVBoxLayout()
        center.setAlignment(Qt.AlignHCenter)

        title = QLabel("Pin kodni kiriting")
        title.setStyleSheet("color: white; font-size: 22px; font-weight: 600;")
        center.addWidget(title)

        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setPlaceholderText("Pin")
        self.pin.setFixedWidth(360)
        self.pin.setFixedHeight(44)

        # 🔧 Siz so‘ragan: #D9D9D9 47% opacity -> rgba(217,217,217,120)
        self.pin.setStyleSheet("""
            QLineEdit {
                background: rgba(217,217,217,120);
                border: 1px solid rgba(255,255,255,40);
                border-radius: 22px;
                padding-left: 16px;
                color: white;
                font-size: 16px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(255,255,255,120);
            }
        """)
        self.pin.returnPressed.connect(self.try_login)
        center.addSpacing(10)
        center.addWidget(self.pin)

        root.addLayout(center)
        root.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def try_login(self):
        if self.pin.text().strip() == PIN_CODE:
            self.pin.clear()
            self.on_success()
        else:
            QMessageBox.warning(self, "Xato", "PIN noto‘g‘ri!")


# =========================================================
# SIDE DRAWER (Slide panel)
# =========================================================
class SideDrawer(QFrame):
    def __init__(self, on_home, on_admin):
        super().__init__()
        self.on_home = on_home
        self.on_admin = on_admin
        self.opened = True

        self.setStyleSheet("""
            QFrame {
                background: rgba(200,200,200,0.35);
            }
        """)
        self.setFixedWidth(220)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        # logo (home)
        self.logo_btn = make_logo_button(self.on_home)
        lay.addWidget(self.logo_btn, alignment=Qt.AlignLeft)

        lay.addSpacing(10)

        self.admin_btn = QPushButton("Admin paneli")
        self.admin_btn.setCursor(Qt.PointingHandCursor)
        self.admin_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 10px 12px;
                border-radius: 10px;
                color: white;
                font-size: 14px;
                background: rgba(0,0,0,0.25);
            }
            QPushButton:hover { background: rgba(0,0,0,0.35); }
        """)
        self.admin_btn.clicked.connect(self.on_admin)
        lay.addWidget(self.admin_btn)

        lay.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        gear = QLabel("⚙️")
        gear.setStyleSheet("color: white; font-size: 24px;")
        lay.addWidget(gear, alignment=Qt.AlignLeft)


class DrawerToggleButton(QPushButton):
    def __init__(self, on_click):
        super().__init__("◀")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 46)
        self.setStyleSheet("""
            QPushButton {
                background: #2F52FF;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 18px;
                font-weight: 700;
            }
            QPushButton:hover { background: #2747E6; }
        """)
        self.clicked.connect(on_click)

    def set_opened(self, opened: bool):
        self.setText("◀" if opened else "▶")


# =========================================================
# MAIN PAGE (6 tables)
# =========================================================
class MainPage(BackgroundWidget):
    def __init__(self, sessions: Dict[int, TableSession], open_table, open_admin):
        super().__init__(MAIN_BG)
        self.sessions = sessions
        self.open_table = open_table
        self.open_admin = open_admin

        self.root = QHBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

        self.drawer = SideDrawer(on_home=self.go_home, on_admin=self.open_admin)
        self.root.addWidget(self.drawer)

        self.toggle = DrawerToggleButton(self.toggle_drawer)

        self.content = QWidget()
        self.root.addWidget(self.content, 1)

        content_lay = QVBoxLayout(self.content)
        content_lay.setContentsMargins(20, 20, 20, 20)

        # toggle button left overlay row
        top_row = QHBoxLayout()
        top_row.addWidget(self.toggle, alignment=Qt.AlignLeft)
        top_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        content_lay.addLayout(top_row)

        grid_wrap = QWidget()
        content_lay.addWidget(grid_wrap, 1)

        self.grid = QGridLayout(grid_wrap)
        self.grid.setContentsMargins(40, 10, 40, 40)
        self.grid.setHorizontalSpacing(30)
        self.grid.setVerticalSpacing(30)

        self.table_buttons: Dict[int, QPushButton] = {}

        # 2x3
        idx = 1
        for r in range(2):
            for c in range(3):
                btn = QPushButton()
                btn.setCursor(Qt.PointingHandCursor)
                btn.setMinimumSize(180, 140)
                btn.clicked.connect(lambda _, n=idx: self.open_table(n))

                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(0,0,0,0.30);
                        border: 1px solid rgba(255,255,255,40);
                        border-radius: 18px;
                        color: white;
                        font-size: 18px;
                        font-weight: 600;
                    }
                    QPushButton:hover { background: rgba(0,0,0,0.40); }
                """)
                self.grid.addWidget(btn, r, c)
                self.table_buttons[idx] = btn
                idx += 1

        self.refresh()

        # refresh statuses every second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

        # drawer animation
        self.anim = QPropertyAnimation(self.drawer, b"maximumWidth", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)

    def go_home(self):
        # already home
        pass

    def toggle_drawer(self):
        opened = self.drawer.width() > 80
        if opened:
            self.toggle.set_opened(False)
            self.anim.stop()
            self.drawer.setMaximumWidth(self.drawer.width())
            self.anim.setStartValue(self.drawer.width())
            self.anim.setEndValue(70)
            self.anim.start()
        else:
            self.toggle.set_opened(True)
            self.anim.stop()
            self.drawer.setMaximumWidth(self.drawer.width())
            self.anim.setStartValue(self.drawer.width())
            self.anim.setEndValue(220)
            self.anim.start()

    def refresh(self):
        for n, btn in self.table_buttons.items():
            busy = self.sessions[n].running or self.sessions[n].elapsed_seconds > 0
            status = "BAND" if busy else "BO‘SH"
            btn.setText(f"{n}-stol\n[{status}]")
            if busy:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(255,0,0,0.18);
                        border: 1px solid rgba(255,255,255,60);
                        border-radius: 18px;
                        color: white;
                        font-size: 18px;
                        font-weight: 700;
                    }
                    QPushButton:hover { background: rgba(255,0,0,0.25); }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(0,0,0,0.30);
                        border: 1px solid rgba(255,255,255,40);
                        border-radius: 18px;
                        color: white;
                        font-size: 18px;
                        font-weight: 600;
                    }
                    QPushButton:hover { background: rgba(0,0,0,0.40); }
                """)


# =========================================================
# ADMIN PAGE
# =========================================================
class AdminPage(BackgroundWidget):
    def __init__(self, go_home, on_products_changed):
        super().__init__(MAIN_BG)  # admin ham shu fon ustida
        self.go_home = go_home
        self.on_products_changed = on_products_changed
        self.selected_image: Optional[str] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.drawer = SideDrawer(on_home=self.go_home, on_admin=lambda: None)
        root.addWidget(self.drawer)

        content = QWidget()
        root.addWidget(content, 1)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)

        # top logo + title
        top = QHBoxLayout()
        top.addWidget(make_logo_button(self.go_home), alignment=Qt.AlignLeft)
        t = QLabel("Mahsulot kiritish")
        t.setStyleSheet("color: white; font-size: 26px; font-weight: 700;")
        top.addWidget(t)
        top.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        lay.addLayout(top)

        form = QFrame()
        form.setStyleSheet("""
            QFrame {
                background: rgba(220,220,220,0.50);
                border-radius: 18px;
            }
        """)
        lay.addWidget(form, 0)

        f = QVBoxLayout(form)
        f.setContentsMargins(18, 18, 18, 18)
        f.setSpacing(12)

        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("Mahsulot nomini yozing")
        self.size_in = QLineEdit()
        self.size_in.setPlaceholderText("Mahsulot hajmini yozing")
        self.price_in = QLineEdit()
        self.price_in.setPlaceholderText("Mahsulot narxini yozing (faqat raqam)")
        self.price_in.setInputMask("999999999")  # raqam

        for w in (self.name_in, self.size_in, self.price_in):
            w.setFixedHeight(40)
            w.setStyleSheet("""
                QLineEdit {
                    background: rgba(240,240,240,0.85);
                    border: 1px solid rgba(0,0,0,40);
                    border-radius: 12px;
                    padding-left: 12px;
                    font-size: 14px;
                    color: #111;
                }
            """)
            w.textChanged.connect(self.validate)

        # image row
        img_row = QHBoxLayout()
        img_lbl = QLabel("Mahsulotning rasmini joylang:")
        img_lbl.setStyleSheet("color: #111; font-size: 14px; font-weight: 600;")
        img_row.addWidget(img_lbl)

        self.pick_btn = QPushButton("🖼️ Upload")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,0,0,0.12);
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 700;
            }
            QPushButton:hover { background: rgba(0,0,0,0.18); }
        """)
        self.pick_btn.clicked.connect(self.pick_image)

        self.img_info = QLabel("(rasm tanlanmagan)")
        self.img_info.setStyleSheet("color: #222;")

        img_row.addWidget(self.pick_btn)
        img_row.addWidget(self.img_info, 1)
        f.addWidget(self.name_in)
        f.addWidget(self.size_in)
        f.addLayout(img_row)
        f.addWidget(self.price_in)

        # add button
        self.add_btn = QPushButton("Qo‘shish")
        self.add_btn.setEnabled(False)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setFixedHeight(46)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #3C45FF;
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 16px;
                font-weight: 800;
            }
            QPushButton:disabled { background: rgba(60,69,255,0.35); }
            QPushButton:hover:!disabled { background: #2F37F0; }
        """)
        self.add_btn.clicked.connect(self.add_product)

        btn_row = QHBoxLayout()
        btn_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        btn_row.addWidget(self.add_btn, 0)
        f.addLayout(btn_row)

        lay.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Rasm tanlang", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.selected_image = path
            self.img_info.setText(os.path.basename(path))
        self.validate()

    def validate(self):
        ok = (
            self.name_in.text().strip() != "" and
            self.size_in.text().strip() != "" and
            self.selected_image is not None and
            self.price_in.text().strip() != ""
        )
        self.add_btn.setEnabled(ok)

    def add_product(self):
        try:
            price = int(self.price_in.text().strip())
        except Exception:
            QMessageBox.warning(self, "Xato", "Narx faqat raqam bo‘lsin!")
            return

        db_add_product(
            self.name_in.text(),
            self.size_in.text(),
            price,
            self.selected_image
        )

        # reset form
        self.name_in.clear()
        self.size_in.clear()
        self.price_in.clear()
        self.selected_image = None
        self.img_info.setText("(rasm tanlanmagan)")
        self.validate()

        QMessageBox.information(self, "OK", "Mahsulot qo‘shildi!")
        self.on_products_changed()


# =========================================================
# TABLE PAGE
# =========================================================
class TablePage(BackgroundWidget):
    def __init__(self, sessions: Dict[int, TableSession], go_home):
        super().__init__(TABLE_BG)
        self.sessions = sessions
        self.go_home = go_home

        self.table_no: int = 1
        self.products: List[dict] = []
        self.product_widgets = {}

        # layout
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # top bar
        top = QHBoxLayout()
        self.logo_btn = make_logo_button(self.go_home)
        top.addWidget(self.logo_btn, alignment=Qt.AlignLeft)

        self.title = QLabel(APP_NAME)
        self.title.setStyleSheet("color: #111; font-size: 36px; font-weight: 800;")
        top.addWidget(self.title)
        top.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        root.addLayout(top)

        # middle: products scroll (left)
        mid = QHBoxLayout()
        root.addLayout(mid, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.scroll_content = QWidget()
        self.scroll.setWidget(self.scroll_content)
        self.prod_lay = QVBoxLayout(self.scroll_content)
        self.prod_lay.setContentsMargins(0, 0, 0, 0)
        self.prod_lay.setSpacing(12)

        mid.addWidget(self.scroll, 1)

        # bottom bar (timer + start/finish)
        bottom = QHBoxLayout()
        bottom.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.timer_box = QLabel("00:00:00")
        self.timer_box.setAlignment(Qt.AlignCenter)
        self.timer_box.setFixedSize(220, 46)
        self.timer_box.setStyleSheet("""
            QLabel {
                background: rgba(220,220,220,0.85);
                border-radius: 10px;
                font-size: 18px;
                font-weight: 800;
                color: #111;
            }
        """)
        bottom.addWidget(self.timer_box)

        bottom.addSpacing(16)

        self.start_btn = QPushButton("Start")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setFixedSize(170, 56)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: rgba(220,220,220,0.90);
                border-radius: 28px;
                font-size: 18px;
                font-weight: 900;
                color: #111;
            }
            QPushButton:hover { background: rgba(235,235,235,0.95); }
        """)
        self.start_btn.clicked.connect(self.toggle_start_finish)
        bottom.addWidget(self.start_btn)

        root.addLayout(bottom)

        # tick timer
        self.tmr = QTimer(self)
        self.tmr.timeout.connect(self.on_tick)
        self.tmr.start(500)

    def set_table(self, table_no: int):
        self.table_no = table_no
        self.reload_products()
        self.refresh_ui()

    def reload_products(self):
        self.products = db_get_products()
        # rebuild list
        # clear
        while self.prod_lay.count():
            item = self.prod_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # build cards
        for p in reversed(self.products):  # older first or reverse? change as you like
            self.prod_lay.addWidget(self.make_product_card(p))

        self.prod_lay.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def make_product_card(self, p: dict) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: rgba(0,0,0,0.18);
                border: 1px solid rgba(255,255,255,35);
                border-radius: 18px;
            }
        """)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        # image
        img = QLabel()
        img.setFixedSize(74, 74)
        img.setStyleSheet("background: rgba(255,255,255,0.85); border-radius: 16px;")
        if os.path.exists(p["image"]):
            pix = QPixmap(p["image"]).scaled(62, 62, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img.setPixmap(pix)
            img.setAlignment(Qt.AlignCenter)
        lay.addWidget(img)

        # name + price
        info = QVBoxLayout()
        name = QLabel(f'{p["name"]}  ({p["size"]})')
        name.setStyleSheet("color: white; font-size: 16px; font-weight: 800;")
        price = QLabel(format_sum(int(p["price"])))
        price.setStyleSheet("color: white; font-size: 14px; font-weight: 700;")
        info.addWidget(name)
        info.addWidget(price)
        lay.addLayout(info, 1)

        # qty + plus
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignRight)

        qty_lbl = QLabel("0")
        qty_lbl.setStyleSheet("color: white; font-size: 18px; font-weight: 900;")
        qty_lbl.setAlignment(Qt.AlignRight)

        plus = QPushButton("+")
        plus.setCursor(Qt.PointingHandCursor)
        plus.setFixedSize(44, 44)
        plus.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.88);
                border: none;
                border-radius: 22px;
                font-size: 22px;
                font-weight: 900;
                color: #111;
            }
            QPushButton:hover { background: rgba(255,255,255,0.98); }
        """)

        def add_one():
            sess = self.sessions[self.table_no]
            pid = p["id"]
            sess.cart[pid] = sess.cart.get(pid, 0) + 1
            qty_lbl.setText(str(sess.cart[pid]))

        plus.clicked.connect(add_one)

        right.addWidget(qty_lbl)
        right.addWidget(plus)
        lay.addLayout(right)

        # keep for refresh
        self.product_widgets[p["id"]] = qty_lbl
        return card

    def refresh_ui(self):
        sess = self.sessions[self.table_no]
        self.timer_box.setText(seconds_to_hms(sess.elapsed_seconds))
        self.start_btn.setText("Finish" if sess.running else "Start")

        # qty refresh
        for pid, lbl in self.product_widgets.items():
            lbl.setText(str(sess.cart.get(pid, 0)))

    def on_tick(self):
        sess = self.sessions[self.table_no]
        sess.tick()
        self.timer_box.setText(seconds_to_hms(sess.elapsed_seconds))

        # text start/finish
        self.start_btn.setText("Finish" if sess.running else "Start")

    def toggle_start_finish(self):
        sess = self.sessions[self.table_no]
        if not sess.running:
            # START
            sess.start()
            self.refresh_ui()
        else:
            # FINISH
            sess.stop()
            self.finish_session()

    def finish_session(self):
        sess = self.sessions[self.table_no]

        # hisob
        table_cost = calc_table_cost(sess.elapsed_seconds)

        # bar items -> list
        products_map = {p["id"]: p for p in db_get_products()}
        items = []
        bar_cost = 0
        for pid, qty in sess.cart.items():
            if qty <= 0:
                continue
            p = products_map.get(pid)
            if not p:
                continue
            items.append({"name": p["name"], "price": int(p["price"]), "qty": int(qty)})
            bar_cost += int(p["price"]) * int(qty)

        total = table_cost + bar_cost

        rid = db_add_receipt(
            table_no=sess.table_no,
            seconds=sess.elapsed_seconds,
            table_cost=table_cost,
            bar_cost=bar_cost,
            total=total,
            items=items
        )

        # chek dialog
        lines = []
        lines.append(f"Chek № {rid}")
        lines.append(f"Stol: {sess.table_no}")
        lines.append(f"Vaqt: {seconds_to_hms(sess.elapsed_seconds)}")
        lines.append(f"Stol: {format_sum(table_cost)}")
        lines.append("")
        lines.append("Bar:")
        if items:
            for it in items:
                lines.append(f' - {it["name"]} x{it["qty"]} = {format_sum(it["price"] * it["qty"])}')
        else:
            lines.append(" - (hech narsa olinmadi)")
        lines.append("")
        lines.append(f"Bar jami: {format_sum(bar_cost)}")
        lines.append(f"JAMI: {format_sum(total)}")
        lines.append("")
        lines.append("To‘lov: NAQD ✅")

        QMessageBox.information(self, "Finish (NAQD)", "\n".join(lines))

        # reset session -> Startga qaytadi
        sess.running = False
        sess.elapsed_seconds = 0
        sess.cart.clear()
        self.refresh_ui()


# =========================================================
# MAIN WINDOW + NAV
# =========================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # app header
        self.setWindowTitle(APP_NAME)
        if os.path.exists(APP_ICON_ICO):
            self.setWindowIcon(QIcon(APP_ICON_ICO))

        self.setMinimumSize(1000, 650)
        self.showMaximized()  # 🔧 xohlasangiz comment qiling

        # sessions
        self.sessions: Dict[int, TableSession] = {i: TableSession(i) for i in range(1, 7)}

        # stacked pages
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login = LoginPage(on_success=self.goto_main)
        self.main = MainPage(
            sessions=self.sessions,
            open_table=self.open_table,
            open_admin=self.goto_admin
        )
        self.admin = AdminPage(go_home=self.goto_main, on_products_changed=self.on_products_changed)
        self.table = TablePage(sessions=self.sessions, go_home=self.goto_main)

        self.stack.addWidget(self.login)  # 0
        self.stack.addWidget(self.main)   # 1
        self.stack.addWidget(self.admin)  # 2
        self.stack.addWidget(self.table)  # 3

        self.stack.setCurrentWidget(self.login)

    def goto_main(self):
        self.stack.setCurrentWidget(self.main)

    def goto_admin(self):
        self.stack.setCurrentWidget(self.admin)

    def goto_main_from_logo(self):
        self.goto_main()

    def on_products_changed(self):
        # stol oynasi ochiq bo‘lsa ham yangilash imkoniyati
        if self.stack.currentWidget() == self.table:
            self.table.reload_products()

    def open_table(self, table_no: int):
        self.table.set_table(table_no)
        self.stack.setCurrentWidget(self.table)


def apply_modern_style(app: QApplication):
    # Telegramga yaqin “clean” ko‘rinish uchun
    app.setStyle("Fusion")
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)


if __name__ == "__main__":
    # prepare
    os.makedirs("assets", exist_ok=True)
    os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)
    db_init()

    app = QApplication([])
    app.setApplicationName(APP_NAME)
    if os.path.exists(APP_ICON_ICO):
        app.setWindowIcon(QIcon(APP_ICON_ICO))
    apply_modern_style(app)

    w = MainWindow()
    w.show()

    app.exec()
