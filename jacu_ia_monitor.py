"""
jacu.ia monitor - Windows 11 Gadget / HUD Monitoring Tool
---------------------------------------------------------
Author: jacu.ia
Description:
    Lightweight, modern desktop gadget for Windows 11 built with PyQt6.
    Monitors servers and network services (ICMP Ping, TCP Ports, HTTP/HTTPS endpoints).
    Features:
      - Always-On-Top toggleable floating gadget mode.
      - Frameless, translucent dark mode UI with Windows 11 aesthetic.
      - Dynamic JSON-based configuration stored in `amonitorar.txt`.
      - Real-time LED indicator & sparkline heartbeat latency graph.
      - Non-blocking background worker threads with customizable interval per target.
      - Integrated visual manager to add, edit, test, and remove monitors.
"""

import sys
import os
import json
import time
import socket
import subprocess
import platform
import urllib.request
import urllib.error
from typing import List, Dict, Any

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPoint, QRectF, QTimer
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPainterPath, QFont, QIcon, QMouseEvent
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QScrollArea, QDialog,
    QLineEdit, QComboBox, QSpinBox, QMessageBox, QFrame,
    QGraphicsDropShadowEffect, QSlider, QSizeGrip
)

CONFIG_FILENAME = "amonitorar.txt"

# Default configuration template if file does not exist
DEFAULT_CONFIG = {
    "opacity": 92,
    "window": {
        "x": 100,
        "y": 100,
        "width": 350,
        "height": 480
    },
    "monitors": [
        {
            "id": "srv-1",
            "name": "Cloudflare DNS",
            "type": "PING",
            "target": "1.1.1.1",
            "port": 0,
            "interval": 5
        },
        {
            "id": "srv-2",
            "name": "Google DNS",
            "type": "PING",
            "target": "8.8.8.8",
            "port": 0,
            "interval": 5
        },
        {
            "id": "srv-3",
            "name": "Web Portal (HTTPS)",
            "type": "HTTP",
            "target": "https://www.google.com",
            "port": 443,
            "interval": 10
        },
        {
            "id": "srv-4",
            "name": "SSH Gateway",
            "type": "TCP",
            "target": "github.com",
            "port": 22,
            "interval": 8
        }
    ]
}


# ============================================================================
#  Data Persistence Helpers
# ============================================================================

def load_config() -> Dict[str, Any]:
    """Loads configuration and monitor definitions from amonitorar.txt (JSON format)."""
    if not os.path.exists(CONFIG_FILENAME):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILENAME, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Backward-compatibility if amonitorar.txt was previously just a list
            if isinstance(data, list):
                return {"opacity": 92, "window": DEFAULT_CONFIG["window"], "monitors": data}
            if isinstance(data, dict):
                if "monitors" not in data:
                    data["monitors"] = []
                if "opacity" not in data:
                    data["opacity"] = 92
                if "window" not in data or not isinstance(data["window"], dict):
                    data["window"] = dict(DEFAULT_CONFIG["window"])
                return data
            return DEFAULT_CONFIG
    except Exception as e:
        print(f"Error reading {CONFIG_FILENAME}: {e}")
        return DEFAULT_CONFIG


def save_config(data: Dict[str, Any]):
    """Saves entire configuration (monitors and settings) to amonitorar.txt."""
    try:
        with open(CONFIG_FILENAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving {CONFIG_FILENAME}: {e}")


# ============================================================================
#  Network Verification Logic
# ============================================================================

def check_ping(host: str, timeout_sec: float = 2.0) -> (bool, float):
    """Executes an ICMP echo ping and calculates latency in ms."""
    param = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
    # Windows -w is in milliseconds
    timeout_val = str(int(timeout_sec * 1000)) if platform.system().lower() == "windows" else str(int(timeout_sec))

    command = ["ping", param, "1", timeout_param, timeout_val, host]
    start_time = time.time()
    try:
        creationflags = 0x08000000 if platform.system().lower() == "windows" else 0  # CREATE_NO_WINDOW
        res = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            timeout=timeout_sec + 0.5
        )
        latency = (time.time() - start_time) * 1000.0
        return (res.returncode == 0, round(latency, 1))
    except Exception:
        return (False, 0.0)


def check_tcp(host: str, port: int, timeout_sec: float = 2.0) -> (bool, float):
    """Checks raw TCP socket connection (e.g. SSH, MySQL, Postgres, Telnet)."""
    start_time = time.time()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_sec)
    try:
        s.connect((host, port))
        latency = (time.time() - start_time) * 1000.0
        s.close()
        return (True, round(latency, 1))
    except Exception:
        return (False, 0.0)


def check_http(url: str, timeout_sec: float = 3.0) -> (bool, float):
    """Checks HTTP/HTTPS endpoint availability and response speed."""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url

    start_time = time.time()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "jacu.ia-monitor/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            latency = (time.time() - start_time) * 1000.0
            status_ok = (200 <= response.status < 400)
            return (status_ok, round(latency, 1))
    except urllib.error.HTTPError as e:
        # HTTP errors like 401 Unauthorized or 403 Forbidden indicate the host & service are alive
        latency = (time.time() - start_time) * 1000.0
        return (e.code < 500, round(latency, 1))
    except Exception:
        return (False, 0.0)


# ============================================================================
#  Worker Thread
# ============================================================================

class MonitorWorker(QThread):
    """Background worker thread for an individual monitor item."""
    result_ready = pyqtSignal(str, bool, float)  # id, is_up, latency_ms

    def __init__(self, monitor_data: Dict[str, Any]):
        super().__init__()
        self.data = monitor_data
        self.is_running = True

    def run(self):
        while self.is_running:
            m_type = self.data.get("type", "PING").upper()
            target = self.data.get("target", "")
            port = int(self.data.get("port", 0))
            is_up, latency = False, 0.0

            if m_type == "PING":
                is_up, latency = check_ping(target)
            elif m_type == "TCP":
                is_up, latency = check_tcp(target, port)
            elif m_type == "HTTP":
                is_up, latency = check_http(target)

            self.result_ready.emit(self.data.get("id"), is_up, latency)

            interval = max(2, int(self.data.get("interval", 5)))
            for _ in range(interval * 10):
                if not self.is_running:
                    break
                time.sleep(0.1)

    def stop(self):
        self.is_running = False
        self.wait()


# ============================================================================
#  Custom UI Components: Sparkline Latency Graph & LED
# ============================================================================

class SparklineWidget(QWidget):
    """Miniature heartbeat / latency sparkline with loss visualization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: List[float] = []
        self.max_points = 24
        self.setFixedHeight(32)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def add_metric(self, is_up: bool, latency: float):
        # Store negative or zero value if down to represent packet loss / outage
        val = latency if is_up else -1.0
        self.history.append(val)
        if len(self.history) > self.max_points:
            self.history.pop(0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Canvas background box
        painter.setBrush(QBrush(QColor(18, 22, 29, 180)))
        painter.setPen(QPen(QColor(255, 255, 255, 12), 1))
        painter.drawRoundedRect(0, 0, w, h, 4, 4)

        if not self.history:
            return

        # Find max latency to scale (minimum 50ms scale for visual stability)
        valid_lats = [x for x in self.history if x >= 0]
        max_lat = max(valid_lats) if valid_lats else 100.0
        max_scale = max(max_lat * 1.2, 50.0)

        step_x = (w - 8) / max(1, self.max_points - 1)
        points = []

        for i, val in enumerate(self.history):
            x = 4 + i * step_x
            if val < 0:
                y = h - 4  # Dropped packet stays near bottom
            else:
                ratio = min(val / max_scale, 1.0)
                y = (h - 6) - (ratio * (h - 12))
            points.append((x, y, val))

        # Draw area under sparkline
        if len(points) > 1:
            poly_path = QPainterPath()
            poly_path.moveTo(points[0][0], h - 3)
            for pt in points:
                poly_path.lineTo(pt[0], pt[1])
            poly_path.lineTo(points[-1][0], h - 3)
            poly_path.closeSubpath()

            # Semi-transparent gradient fill
            fill_color = QColor(16, 185, 129, 45) if (self.history[-1] >= 0) else QColor(239, 68, 68, 45)
            painter.fillPath(poly_path, QBrush(fill_color))

        # Draw sparkline path
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            if p2[2] < 0:
                line_pen = QPen(QColor(239, 68, 68, 220), 1.5, Qt.PenStyle.DashLine)
            else:
                line_pen = QPen(QColor(52, 211, 153, 230), 1.8)

            painter.setPen(line_pen)
            painter.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))

        # Pulse circle at head
        if points:
            last = points[-1]
            head_color = QColor(52, 211, 153) if last[2] >= 0 else QColor(239, 68, 68)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(head_color))
            painter.drawEllipse(QPoint(int(last[0]), int(last[1])), 2, 2)


class StatusLed(QWidget):
    """Glowing LED indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.is_up = True
        self.has_data = False

    def set_status(self, is_up: bool):
        self.is_up = is_up
        self.has_data = True
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.has_data:
            base_col = QColor(148, 163, 184)  # Slate pending
            glow_col = QColor(148, 163, 184, 50)
        elif self.is_up:
            base_col = QColor(16, 185, 129)  # Emerald UP
            glow_col = QColor(16, 185, 129, 70)
        else:
            base_col = QColor(239, 68, 68)  # Crimson ALARM
            glow_col = QColor(239, 68, 68, 80)

        # Glow halo
        painter.setBrush(QBrush(glow_col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 12, 12)

        # Bright center dot
        painter.setBrush(QBrush(base_col))
        painter.drawEllipse(3, 3, 8, 8)


# ============================================================================
#  Monitor Card Widget
# ============================================================================

class MonitorCard(QFrame):
    """Compact individual monitor tile."""
    double_clicked = pyqtSignal(str)

    def __init__(self, data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.data = data
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clique duplo para editar as configurações deste serviço")
        self.setObjectName("monitorCard")
        self.setStyleSheet("""
            QFrame#monitorCard {
                background-color: rgba(30, 36, 48, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QFrame#monitorCard:hover {
                background-color: rgba(38, 46, 61, 0.88);
                border: 1px solid rgba(59, 130, 246, 0.35);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Top row: LED, Service Name, Type Tag
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        self.led = StatusLed()
        top_layout.addWidget(self.led)

        self.lbl_name = QLabel(data.get("name", "Unknown"))
        self.lbl_name.setStyleSheet("font-size: 12px; font-weight: 600; color: #F1F5F9;")
        top_layout.addWidget(self.lbl_name, 1)

        type_text = data.get("type", "PING").upper()
        self.lbl_tag = QLabel(type_text)
        self.lbl_tag.setStyleSheet("""
            background-color: rgba(59, 130, 246, 0.20);
            color: #60A5FA;
            font-size: 9px;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 4px;
        """)
        top_layout.addWidget(self.lbl_tag)

        layout.addLayout(top_layout)

        # Sub-info row: Target & Latency readout
        sub_layout = QHBoxLayout()
        sub_layout.setContentsMargins(0, 0, 0, 0)

        target_display = str(data.get("target", ""))
        if data.get("port") and int(data.get("port")) > 0:
            target_display += f":{data.get('port')}"
        if len(target_display) > 24:
            target_display = target_display[:22] + "…"

        self.lbl_target = QLabel(target_display)
        self.lbl_target.setStyleSheet("font-size: 10px; color: #94A3B8;")
        sub_layout.addWidget(self.lbl_target, 1)

        self.lbl_metric = QLabel("Checking…")
        self.lbl_metric.setStyleSheet("font-size: 10px; font-weight: 600; color: #94A3B8;")
        sub_layout.addWidget(self.lbl_metric)

        layout.addLayout(sub_layout)

        # Heartbeat latency sparkline
        self.sparkline = SparklineWidget()
        layout.addWidget(self.sparkline)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.data.get("id"))
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def update_status(self, is_up: bool, latency: float):
        self.led.set_status(is_up)
        self.sparkline.add_metric(is_up, latency)
        if is_up:
            self.lbl_metric.setText(f"{latency:.0f} ms")
            self.lbl_metric.setStyleSheet("font-size: 10px; font-weight: 600; color: #34D399;")
        else:
            self.lbl_metric.setText("ALARM / DOWN")
            self.lbl_metric.setStyleSheet("font-size: 10px; font-weight: 700; color: #F87171;")


# ============================================================================
#  Service Edit Modal Dialog
# ============================================================================

class EditServiceDialog(QDialog):
    """Dialog to edit an existing monitored target."""

    def __init__(self, monitor_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Editar: {monitor_data.get('name', 'Serviço')}")
        self.resize(440, 320)
        self.setModal(True)
        self.monitor_data = dict(monitor_data)

        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Segoe UI', Inter, sans-serif;
            }
            QLabel {
                color: #CBD5E1;
                font-size: 11px;
                font-weight: 600;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                color: #F8FAFC;
                padding: 6px 8px;
                border-radius: 6px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #3B82F6;
            }
            QPushButton {
                font-weight: 600;
                padding: 7px 14px;
                border-radius: 6px;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(f"Editar Monitoramento - ID: {self.monitor_data.get('id')}")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title)

        form_grid = QGridLayout()
        form_grid.setSpacing(8)

        form_grid.addWidget(QLabel("Nome do Serviço:"), 0, 0)
        self.txt_name = QLineEdit(self.monitor_data.get("name", ""))
        form_grid.addWidget(self.txt_name, 0, 1)

        form_grid.addWidget(QLabel("Tipo de Checagem:"), 1, 0)
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["PING", "TCP", "HTTP"])
        current_type = self.monitor_data.get("type", "PING").upper()
        idx = self.cmb_type.findText(current_type)
        if idx >= 0:
            self.cmb_type.setCurrentIndex(idx)
        self.cmb_type.currentTextChanged.connect(self.on_type_changed)
        form_grid.addWidget(self.cmb_type, 1, 1)

        form_grid.addWidget(QLabel("Endereço IP ou URL:"), 2, 0)
        self.txt_target = QLineEdit(self.monitor_data.get("target", ""))
        form_grid.addWidget(self.txt_target, 2, 1)

        self.lbl_port = QLabel("Porta:")
        form_grid.addWidget(self.lbl_port, 3, 0)
        self.spn_port = QSpinBox()
        self.spn_port.setRange(0, 65535)
        self.spn_port.setValue(int(self.monitor_data.get("port", 0)))
        self.spn_port.setEnabled(current_type == "TCP")
        form_grid.addWidget(self.spn_port, 3, 1)

        form_grid.addWidget(QLabel("Intervalo de Coleta (s):"), 4, 0)
        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(2, 3600)
        self.spn_interval.setValue(int(self.monitor_data.get("interval", 5)))
        form_grid.addWidget(self.spn_interval, 4, 1)

        layout.addLayout(form_grid)
        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet("background-color: #334155; color: #E2E8F0;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_save = QPushButton("Salvar Alterações")
        btn_save.setStyleSheet("background-color: #2563EB; color: #FFFFFF;")
        btn_save.clicked.connect(self.save)
        btn_box.addWidget(btn_save)

        layout.addLayout(btn_box)

    def on_type_changed(self, text: str):
        if text == "TCP":
            self.spn_port.setEnabled(True)
            if self.spn_port.value() == 0:
                self.spn_port.setValue(80)
        else:
            self.spn_port.setEnabled(False)
            self.spn_port.setValue(0)

    def save(self):
        name = self.txt_name.text().strip()
        target = self.txt_target.text().strip()
        if not name or not target:
            msg = QMessageBox(self)
            msg.setWindowTitle("Campos Obrigatórios")
            msg.setText("Por favor, preencha o Nome e o Endereço IP / URL.")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.exec()
            return

        self.monitor_data["name"] = name
        self.monitor_data["target"] = target
        self.monitor_data["type"] = self.cmb_type.currentText()
        self.monitor_data["port"] = self.spn_port.value() if self.cmb_type.currentText() == "TCP" else 0
        self.monitor_data["interval"] = self.spn_interval.value()
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return self.monitor_data


# ============================================================================
#  Service Manager Modal Dialog
# ============================================================================

class ServiceManagerDialog(QDialog):
    """Dialog allowing users to add, reorder, adjust opacity, and remove monitored targets."""

    def __init__(self, monitors: List[Dict[str, Any]], current_opacity: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações & Painel - jacu.ia monitor")
        self.resize(560, 560)
        self.setModal(True)
        self.monitors = [dict(m) for m in monitors]
        self.opacity_val = current_opacity

        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Segoe UI', Inter, sans-serif;
            }
            QLabel {
                color: #CBD5E1;
                font-size: 11px;
                font-weight: 600;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                color: #F8FAFC;
                padding: 6px 8px;
                border-radius: 6px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #3B82F6;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #334155;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #3B82F6;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #60A5FA;
                border: 1px solid #1E293B;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QScrollArea {
                border: 1px solid #1E293B;
                border-radius: 6px;
                background-color: #0B1120;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ----------------- Transparência do Gadget -----------------
        op_box = QHBoxLayout()
        lbl_op_title = QLabel("Transparência do Gadget:")
        lbl_op_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8;")
        op_box.addWidget(lbl_op_title)

        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(20, 100)
        self.slider_opacity.setValue(self.opacity_val)
        self.slider_opacity.valueChanged.connect(self.on_opacity_change)
        op_box.addWidget(self.slider_opacity, 1)

        self.lbl_opacity_val = QLabel(f"{self.opacity_val}%")
        self.lbl_opacity_val.setFixedWidth(40)
        self.lbl_opacity_val.setStyleSheet("color: #38BDF8; font-weight: bold;")
        op_box.addWidget(self.lbl_opacity_val)
        layout.addLayout(op_box)

        # Divider
        div1 = QFrame()
        div1.setFrameShape(QFrame.Shape.HLine)
        div1.setStyleSheet("color: #334155;")
        layout.addWidget(div1)

        # ----------------- Adicionar Novo Alvo -----------------
        title = QLabel("Adicionar Novo Servidor / Serviço")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title)

        form_grid = QGridLayout()
        form_grid.setSpacing(8)

        form_grid.addWidget(QLabel("Nome do Serviço:"), 0, 0)
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Ex: Servidor Produção, Banco MySQL, API Gateway")
        form_grid.addWidget(self.txt_name, 0, 1)

        form_grid.addWidget(QLabel("Tipo de Checagem:"), 1, 0)
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["PING", "TCP", "HTTP"])
        self.cmb_type.currentTextChanged.connect(self.on_type_changed)
        form_grid.addWidget(self.cmb_type, 1, 1)

        form_grid.addWidget(QLabel("Endereço IP ou URL:"), 2, 0)
        self.txt_target = QLineEdit()
        self.txt_target.setPlaceholderText("192.168.1.1 ou https://meusite.com.br")
        form_grid.addWidget(self.txt_target, 2, 1)

        self.lbl_port = QLabel("Porta:")
        form_grid.addWidget(self.lbl_port, 3, 0)
        self.spn_port = QSpinBox()
        self.spn_port.setRange(0, 65535)
        self.spn_port.setValue(0)
        self.spn_port.setEnabled(False)
        form_grid.addWidget(self.spn_port, 3, 1)

        form_grid.addWidget(QLabel("Intervalo de Coleta (s):"), 4, 0)
        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(2, 3600)
        self.spn_interval.setValue(5)
        form_grid.addWidget(self.spn_interval, 4, 1)

        layout.addLayout(form_grid)

        self.btn_add = QPushButton("+ Adicionar ao Monitoramento")
        self.btn_add.clicked.connect(self.add_monitor)
        layout.addWidget(self.btn_add)

        # Divider
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet("color: #334155;")
        layout.addWidget(div2)

        # ----------------- Ordem dos Serviços -----------------
        list_header = QHBoxLayout()
        list_lbl = QLabel("Ordem de Exibição dos Serviços:")
        list_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #F8FAFC;")
        list_header.addWidget(list_lbl)
        list_header.addStretch()
        hint_lbl = QLabel("(Use ▲ e ▼ para ordenar)")
        hint_lbl.setStyleSheet("color: #64748B; font-size: 10px;")
        list_header.addWidget(hint_lbl)
        layout.addLayout(list_header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(8, 8, 8, 8)
        self.list_layout.setSpacing(6)
        self.scroll.setWidget(self.list_container)
        layout.addWidget(self.scroll, 1)

        # Bottom Actions
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_close = QPushButton("Salvar e Aplicar")
        self.btn_close.setStyleSheet("background-color: #10B981; padding: 8px 18px;")
        self.btn_close.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_close)

        layout.addLayout(btn_box)

        self.refresh_list()

    def on_opacity_change(self, val: int):
        self.opacity_val = val
        self.lbl_opacity_val.setText(f"{val}%")
        # Live preview if parent gadget is active
        if self.parent():
            self.parent().setWindowOpacity(val / 100.0)

    def on_type_changed(self, text: str):
        if text == "TCP":
            self.spn_port.setEnabled(True)
            if self.spn_port.value() == 0:
                self.spn_port.setValue(80)
        else:
            self.spn_port.setEnabled(False)
            self.spn_port.setValue(0)

    def move_up(self, index: int):
        if index > 0:
            self.monitors[index - 1], self.monitors[index] = self.monitors[index], self.monitors[index - 1]
            self.refresh_list()

    def move_down(self, index: int):
        if index < len(self.monitors) - 1:
            self.monitors[index + 1], self.monitors[index] = self.monitors[index], self.monitors[index + 1]
            self.refresh_list()

    def refresh_list(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, m in enumerate(self.monitors):
            row = QFrame()
            row.setStyleSheet("""
                QFrame {
                    background-color: #1E293B;
                    border-radius: 6px;
                    border: 1px solid #334155;
                }
            """)
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(8, 6, 8, 6)
            r_lay.setSpacing(6)

            # Reorder Buttons (Up / Down)
            btn_up = QPushButton("▲")
            btn_up.setFixedSize(22, 22)
            btn_up.setEnabled(idx > 0)
            btn_up.setToolTip("Mover para cima")
            btn_up.setStyleSheet("""
                QPushButton {
                    background-color: #334155;
                    font-size: 10px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #3B82F6;
                }
                QPushButton:disabled {
                    background-color: #1E293B;
                    color: #475569;
                }
            """)
            btn_up.clicked.connect(lambda _, i=idx: self.move_up(i))
            r_lay.addWidget(btn_up)

            btn_down = QPushButton("▼")
            btn_down.setFixedSize(22, 22)
            btn_down.setEnabled(idx < len(self.monitors) - 1)
            btn_down.setToolTip("Mover para baixo")
            btn_down.setStyleSheet("""
                QPushButton {
                    background-color: #334155;
                    font-size: 10px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #3B82F6;
                }
                QPushButton:disabled {
                    background-color: #1E293B;
                    color: #475569;
                }
            """)
            btn_down.clicked.connect(lambda _, i=idx: self.move_down(i))
            r_lay.addWidget(btn_down)

            # Position indicator
            num_lbl = QLabel(f"#{idx + 1}")
            num_lbl.setStyleSheet("color: #64748B; font-weight: bold; font-size: 11px;")
            r_lay.addWidget(num_lbl)

            info_text = f"<b>{m.get('name')}</b> [{m.get('type')}] - {m.get('target')}"
            if m.get('port') and int(m.get('port')) > 0:
                info_text += f":{m.get('port')}"
            info_text += f" ({m.get('interval', 5)}s)"

            lbl = QLabel(info_text)
            lbl.setStyleSheet("font-size: 11px; color: #E2E8F0;")
            r_lay.addWidget(lbl, 1)

            btn_edit = QPushButton("Editar")
            btn_edit.setStyleSheet("""
                QPushButton {
                    background-color: #0284C7;
                    font-size: 10px;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #0369A1;
                }
            """)
            btn_edit.clicked.connect(lambda _, i=idx: self.edit_monitor(i))
            r_lay.addWidget(btn_edit)

            btn_del = QPushButton("Remover")
            btn_del.setStyleSheet("""
                QPushButton {
                    background-color: #EF4444;
                    font-size: 10px;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #DC2626;
                }
            """)
            btn_del.clicked.connect(lambda _, i=idx: self.delete_monitor(i))
            r_lay.addWidget(btn_del)

            self.list_layout.addWidget(row)

        self.list_layout.addStretch()

    def edit_monitor(self, index: int):
        if 0 <= index < len(self.monitors):
            diag = EditServiceDialog(self.monitors[index], self)
            if diag.exec() == QDialog.DialogCode.Accepted:
                self.monitors[index] = diag.get_data()
                self.refresh_list()

    def add_monitor(self):
        name = self.txt_name.text().strip()
        target = self.txt_target.text().strip()
        m_type = self.cmb_type.currentText()
        port = self.spn_port.value()
        interval = self.spn_interval.value()

        if not name or not target:
            msg = QMessageBox(self)
            msg.setWindowTitle("Campos Obrigatórios")
            msg.setText("Por favor, preencha o Nome e o Endereço IP / URL.")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.exec()
            return

        new_item = {
            "id": f"item-{int(time.time() * 1000)}",
            "name": name,
            "type": m_type,
            "target": target,
            "port": port if m_type == "TCP" else 0,
            "interval": interval
        }

        self.monitors.append(new_item)
        self.txt_name.clear()
        self.txt_target.clear()
        self.refresh_list()

    def delete_monitor(self, index: int):
        if 0 <= index < len(self.monitors):
            self.monitors.pop(index)
            self.refresh_list()

    def get_updated_monitors(self) -> List[Dict[str, Any]]:
        return self.monitors

    def get_updated_opacity(self) -> int:
        return self.opacity_val


# ============================================================================
#  Main Gadget Window
# ============================================================================

class JacuMonitorGadget(QMainWindow):
    """Main HUD / Gadget application window with Always-on-Top functionality."""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.monitors: List[Dict[str, Any]] = self.config.get("monitors", [])
        self.opacity_val: int = int(self.config.get("opacity", 92))
        self.window_geom = self.config.get("window", {"x": 100, "y": 100, "width": 350, "height": 480})
        self.workers: Dict[str, MonitorWorker] = {}
        self.cards: Dict[str, MonitorCard] = {}
        self.is_always_on_top = True
        self.drag_position = QPoint()

        self.init_window_properties()
        self.init_ui()
        self.start_monitoring()

    def init_window_properties(self):
        self.setWindowTitle("jacu.ia monitor")
        self.setMinimumSize(300, 200)

        # Frameless and translucent acrylic-styled window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self.opacity_val / 100.0)
        self.update_window_flags()
        self.restore_window_geometry()

    def restore_window_geometry(self):
        """Restores position and dimensions, validating against available screens."""
        w = max(300, int(self.window_geom.get("width", 350)))
        h = max(200, int(self.window_geom.get("height", 480)))
        x = int(self.window_geom.get("x", 100))
        y = int(self.window_geom.get("y", 100))

        # Check if saved position is visible on any connected screen
        screens = QApplication.screens()
        is_visible = False
        for screen in screens:
            geom = screen.geometry()
            # If the top-left area is inside one of the monitors
            if geom.intersects(QRectF(x, y, min(w, 100), min(h, 100)).toRect()):
                is_visible = True
                break

        if is_visible:
            self.setGeometry(x, y, w, h)
        else:
            # Fallback to primary screen center if monitor setup changed
            if screens:
                primary = screens[0].availableGeometry()
                fallback_x = primary.x() + (primary.width() - w) // 2
                fallback_y = primary.y() + (primary.height() - h) // 2
                self.setGeometry(fallback_x, fallback_y, w, h)
            else:
                self.resize(w, h)

    def save_window_geometry(self):
        """Saves current window position and size to configuration."""
        pos = self.pos()
        sz = self.size()
        self.config["window"] = {
            "x": pos.x(),
            "y": pos.y(),
            "width": sz.width(),
            "height": sz.height()
        }
        save_config(self.config)

    def update_window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow
        if self.is_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def init_ui(self):
        # Master Container with rounded corners & dark acrylic glass styling
        self.central_container = QFrame(self)
        self.central_container.setObjectName("gadgetContainer")
        self.central_container.setStyleSheet("""
            QFrame#gadgetContainer {
                background-color: rgba(15, 23, 42, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QSizeGrip {
                width: 14px;
                height: 14px;
                background: transparent;
                margin-right: 2px;
                margin-bottom: 2px;
            }
        """)

        # Soft drop shadow for Windows 11 floating HUD feel
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 6)
        self.central_container.setGraphicsEffect(shadow)

        self.setCentralWidget(self.central_container)

        root_layout = QVBoxLayout(self.central_container)
        root_layout.setContentsMargins(12, 10, 12, 6)
        root_layout.setSpacing(6)

        # -----------------------------
        # Header / Drag Bar
        # -----------------------------
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        # Logo / Title
        title_box = QHBoxLayout()
        icon_lbl = QLabel("⚡")
        icon_lbl.setStyleSheet("font-size: 14px; color: #38BDF8;")
        title_box.addWidget(icon_lbl)

        lbl_title = QLabel("jacu.ia")
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #38BDF8; letter-spacing: 0.5px;")
        title_box.addWidget(lbl_title)

        lbl_sub = QLabel("monitor")
        lbl_sub.setStyleSheet("font-size: 13px; font-weight: 400; color: #94A3B8;")
        title_box.addWidget(lbl_sub)

        lbl_version = QLabel("beta 0.1")
        lbl_version.setStyleSheet("""
            background-color: rgba(245, 158, 11, 0.18);
            color: #FBBF24;
            font-size: 9px;
            font-weight: 700;
            padding: 1px 5px;
            border-radius: 4px;
            margin-left: 2px;
        """)
        title_box.addWidget(lbl_version)

        header.addLayout(title_box)
        header.addStretch()

        # Always-on-top toggle button
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setToolTip("Fixar sobre outros programas (Always on Top)")
        self.btn_pin.setFixedSize(26, 26)
        self.btn_pin.setStyleSheet(self._get_pin_btn_style(self.is_always_on_top))
        self.btn_pin.clicked.connect(self.toggle_always_on_top)
        header.addWidget(self.btn_pin)

        # Manage Services Button
        btn_manage = QPushButton("⚙")
        btn_manage.setToolTip("Gerenciar / Adicionar Servidores")
        btn_manage.setFixedSize(26, 26)
        btn_manage.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #CBD5E1;
                border-radius: 5px;
                font-size: 13px;
                border: 1px solid rgba(255, 255, 255, 0.05);
            }
            QPushButton:hover {
                background-color: rgba(59, 130, 246, 0.4);
                color: #FFFFFF;
            }
        """)
        btn_manage.clicked.connect(self.open_manager)
        header.addWidget(btn_manage)

        # Close App Button
        btn_close = QPushButton("✕")
        btn_close.setToolTip("Fechar jacu.ia monitor")
        btn_close.setFixedSize(26, 26)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #94A3B8;
                border-radius: 5px;
                font-size: 11px;
                border: 1px solid rgba(255, 255, 255, 0.05);
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.8);
                color: #FFFFFF;
            }
        """)
        btn_close.clicked.connect(self.quit_application)
        header.addWidget(btn_close)

        root_layout.addLayout(header)

        # -----------------------------
        # Scrollable Cards Viewport
        # -----------------------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(8)

        self.scroll_area.setWidget(self.cards_container)
        root_layout.addWidget(self.scroll_area, 1)

        # Footer row with resize grip
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("Arrastar para redimensionar janela")
        footer_layout.addWidget(self.size_grip)
        root_layout.addLayout(footer_layout)

        # Populate cards
        self.rebuild_cards()

    def _get_pin_btn_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background-color: rgba(59, 130, 246, 0.6);
                    color: #FFFFFF;
                    border-radius: 5px;
                    font-size: 12px;
                    border: 1px solid #3B82F6;
                }
            """
        return """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: #64748B;
                border-radius: 5px;
                font-size: 12px;
                border: 1px solid rgba(255, 255, 255, 0.05);
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
                color: #CBD5E1;
            }
        """

    def rebuild_cards(self):
        # Remove all existing card widgets
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.cards.clear()

        if not self.monitors:
            lbl_empty = QLabel("Nenhum serviço configurado.\nClique no ⚙ para adicionar.")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("color: #64748B; font-size: 11px; padding: 20px;")
            self.cards_layout.addWidget(lbl_empty)
            return

        for m in self.monitors:
            card = MonitorCard(m)
            card.double_clicked.connect(self.edit_monitor_by_id)
            self.cards[m.get("id")] = card
            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch()

    def edit_monitor_by_id(self, monitor_id: str):
        """Opens Edit dialog when user double-clicks a card in the HUD."""
        for idx, m in enumerate(self.monitors):
            if m.get("id") == monitor_id:
                diag = EditServiceDialog(m, self)
                if diag.exec() == QDialog.DialogCode.Accepted:
                    self.monitors[idx] = diag.get_data()
                    self.config["monitors"] = self.monitors
                    save_config(self.config)
                    self.rebuild_cards()
                    self.start_monitoring()
                break

    def start_monitoring(self):
        """Starts worker threads for each configured monitor item."""
        self.stop_all_workers()

        for m in self.monitors:
            m_id = m.get("id")
            worker = MonitorWorker(m)
            worker.result_ready.connect(self.on_metric_received)
            self.workers[m_id] = worker
            worker.start()

    def stop_all_workers(self):
        for worker in self.workers.values():
            worker.stop()
        self.workers.clear()

    def on_metric_received(self, monitor_id: str, is_up: bool, latency: float):
        if monitor_id in self.cards:
            self.cards[monitor_id].update_status(is_up, latency)

    def toggle_always_on_top(self):
        """Toggles window over other active applications."""
        self.is_always_on_top = not self.is_always_on_top
        self.btn_pin.setStyleSheet(self._get_pin_btn_style(self.is_always_on_top))
        self.update_window_flags()

    def open_manager(self):
        """Opens the configuration manager dialog to add/edit/reorder targets and opacity."""
        dialog = ServiceManagerDialog(self.monitors, self.opacity_val, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.monitors = dialog.get_updated_monitors()
            self.opacity_val = dialog.get_updated_opacity()
            self.setWindowOpacity(self.opacity_val / 100.0)

            # Persist changes to amonitorar.txt
            self.config["monitors"] = self.monitors
            self.config["opacity"] = self.opacity_val
            save_config(self.config)

            self.rebuild_cards()
            self.start_monitoring()
        else:
            # Revert opacity preview if canceled
            self.setWindowOpacity(self.opacity_val / 100.0)

    # -------------------------------------------------------------
    # Window dragging handlers for Frameless HUD
    # -------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_position.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.drag_position = QPoint()
        self.save_window_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.save_window_geometry()

    def quit_application(self):
        """Cleanly terminates monitoring threads, saves window state, and exits app."""
        self.save_window_geometry()
        self.stop_all_workers()
        QApplication.quit()

    def closeEvent(self, event):
        self.save_window_geometry()
        self.stop_all_workers()
        event.accept()
        QApplication.quit()


# ============================================================================
#  Application Bootstrap
# ============================================================================

def main():
    # High DPI scaling for crisp Windows 11 rendering
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Global typography
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    gadget = JacuMonitorGadget()
    gadget.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()