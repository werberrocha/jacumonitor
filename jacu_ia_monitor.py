"""
jacu.ia monitor - Windows 11 Gadget / HUD Monitoring Tool
---------------------------------------------------------
Author: jacu.ia
Version: beta 0.55
Description:
    Lightweight, modern desktop gadget for Windows 11 built with PyQt6.
    Monitors servers and network services (ICMP Ping, TCP Ports, HTTP/HTTPS endpoints).
    Features:
      - Always-On-Top toggleable floating gadget mode.
      - Audio alert toggle (mute / unmute) in header for UP and DOWN events.
      - Custom UP/DOWN MP3 sound selection with max 3-second duration validation.
      - Real-time IP & ISP detection before registering DOWN event logs.
      - Public IP & ISP (Operadora) display with 5-minute auto-refresh & double-click force update.
      - Frameless, translucent dark mode UI with Windows 11 aesthetic.
      - Dynamic JSON-based configuration stored in `amonitorar.txt`.
      - Real-time LED indicator & sparkline heartbeat latency graph with timestamps.
      - Non-blocking background worker threads with customizable interval per target.
      - Event-based compact 30-minute rolling logs (initial state and status transitions).
      - Integrated visual manager to add, edit, test, reorder, and remove monitors.
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
from datetime import datetime, timedelta
import re
from typing import List, Dict, Any, Tuple

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPoint, QRectF, QTimer, QEvent, QUrl
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPainterPath, QFont, QMouseEvent
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QScrollArea, QDialog,
    QLineEdit, QComboBox, QSpinBox, QMessageBox, QFrame,
    QGraphicsDropShadowEffect, QSlider, QSizeGrip, QToolTip,
    QFileDialog
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

APP_VERSION = "beta 0.55"
CONFIG_FILENAME = "amonitorar.txt"
LOGS_DIR = "logs"
DEFAULT_UP_SOUND = "up.mp3"
DEFAULT_DOWN_SOUND = "down.mp3"
MAX_SOUND_DURATION_SEC = 3.0

# Configuração padrão caso amonitorar.txt não exista
DEFAULT_CONFIG = {
    "opacity": 92,
    "sound_enabled": True,
    "up_sound": DEFAULT_UP_SOUND,
    "down_sound": DEFAULT_DOWN_SOUND,
    "window": {
        "x": 100,
        "y": 100,
        "width": 350,
        "height": 500
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
    """Carrega as configurações e a lista de serviços do amonitorar.txt."""
    if not os.path.exists(CONFIG_FILENAME):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILENAME, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                res = dict(DEFAULT_CONFIG)
                res["monitors"] = data
                return res
            if isinstance(data, dict):
                if "monitors" not in data:
                    data["monitors"] = []
                if "opacity" not in data:
                    data["opacity"] = 92
                if "sound_enabled" not in data:
                    data["sound_enabled"] = True
                if "up_sound" not in data:
                    data["up_sound"] = DEFAULT_UP_SOUND
                if "down_sound" not in data:
                    data["down_sound"] = DEFAULT_DOWN_SOUND
                if "window" not in data or not isinstance(data["window"], dict):
                    data["window"] = dict(DEFAULT_CONFIG["window"])
                return data
            return DEFAULT_CONFIG
    except Exception as e:
        print(f"Erro ao ler {CONFIG_FILENAME}: {e}")
        return DEFAULT_CONFIG


def save_config(data: Dict[str, Any]):
    """Salva a configuração completa no amonitorar.txt."""
    try:
        with open(CONFIG_FILENAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar {CONFIG_FILENAME}: {e}")


# ============================================================================
#  Log Persistence Helpers (30 minutos, delimitado por |)
# ============================================================================

def append_service_log(monitor_id: str, monitor_target: str, is_up: bool, latency: float, origin_ip: str, origin_isp: str):
    """
    Registra um evento em logs/<monitor_id>.log no formato compacto:
    TIMESTAMP|ORIGIN_IP|ORIGIN_ISP|TARGET|STATUS|LATENCY
    Mantém apenas o histórico dos últimos 30 minutos.
    """
    try:
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR, exist_ok=True)

        safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', monitor_id)
        log_path = os.path.join(LOGS_DIR, f"{safe_id}.log")

        now = datetime.now()
        status_str = "UP" if is_up else "DOWN"
        clean_target = monitor_target.replace("|", "/")
        clean_isp = origin_isp.replace("|", "/")
        clean_ip = origin_ip.replace("|", "/")

        new_entry = f"{now.strftime('%Y-%m-%d %H:%M:%S')}|{clean_ip}|{clean_isp}|{clean_target}|{status_str}|{latency:.1f}\n"

        cutoff_time = now - timedelta(minutes=30)
        kept_lines = []

        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines:
                parts = line.split("|")
                if len(parts) >= 2:
                    ts_part = parts[0].strip()
                    if ts_part.startswith("[") and ts_part.endswith("]"):
                        ts_part = ts_part[1:-1]
                    try:
                        entry_time = datetime.strptime(ts_part, "%Y-%m-%d %H:%M:%S")
                        if entry_time >= cutoff_time:
                            kept_lines.append(line)
                    except ValueError:
                        kept_lines.append(line)
                else:
                    kept_lines.append(line)

        kept_lines.append(new_entry)

        with open(log_path, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)
    except Exception as e:
        print(f"Erro ao gravar log para {monitor_id}: {e}")


# ============================================================================
#  Network Verification Logic
# ============================================================================

def query_current_network_origin(timeout_sec: float = 2.0) -> Tuple[str, str]:
    """Consulta IP público e Provedor atual de forma síncrona."""
    try:
        req = urllib.request.Request(
            "http://ip-api.com/json/?fields=query,isp,status",
            headers={"User-Agent": "jacu.ia-monitor/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            data = json.loads(res.read().decode("utf-8"))
            if data.get("status") == "success":
                return data.get("query", "Desconhecido"), data.get("isp", "Desconhecida")
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            "https://api.ipify.org?format=json",
            headers={"User-Agent": "jacu.ia-monitor/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            data = json.loads(res.read().decode("utf-8"))
            return data.get("ip", "Desconhecido"), "Detectado via Ipify"
    except Exception:
        pass

    return "Indisponível", "Sem rota / Falha de Conexão"


def check_ping(host: str, timeout_sec: float = 2.0) -> Tuple[bool, float]:
    """Realiza ping ICMP e retorna latência em milissegundos."""
    param = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
    timeout_val = str(int(timeout_sec * 1000)) if platform.system().lower() == "windows" else str(int(timeout_sec))

    command = ["ping", param, "1", timeout_param, timeout_val, host]
    start_time = time.time()
    try:
        creationflags = 0x08000000 if platform.system().lower() == "windows" else 0
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


def check_tcp(host: str, port: int, timeout_sec: float = 2.0) -> Tuple[bool, float]:
    """Testa abertura de socket TCP (SSH, Telnet, bancos, etc)."""
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


def check_http(url: str, timeout_sec: float = 3.0) -> Tuple[bool, float]:
    """Testa requisição HTTP/HTTPS."""
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
        latency = (time.time() - start_time) * 1000.0
        return (e.code < 500, round(latency, 1))
    except Exception:
        return (False, 0.0)


# ============================================================================
#  Audio Duration Validator
# ============================================================================

def validate_mp3_duration(filepath: str, max_duration_sec: float = MAX_SOUND_DURATION_SEC) -> Tuple[bool, float, str]:
    """Valida se o áudio existe e não ultrapassa o limite em segundos."""
    if not os.path.exists(filepath):
        return False, 0.0, "Arquivo de áudio não encontrado."

    player = QMediaPlayer()
    audio_output = QAudioOutput()
    player.setAudioOutput(audio_output)
    audio_output.setVolume(0.0)

    resolved_path = os.path.abspath(filepath)
    player.setSource(QUrl.fromLocalFile(resolved_path))

    timeout_counter = 0
    while player.duration() <= 0 and timeout_counter < 30:
        QApplication.processEvents()
        time.sleep(0.05)
        timeout_counter += 1

    dur_ms = player.duration()
    dur_sec = dur_ms / 1000.0

    if dur_sec <= 0:
        try:
            sz = os.path.getsize(resolved_path)
            est_sec = sz / 16000.0
            if est_sec > max_duration_sec + 0.5:
                return False, est_sec, f"Áudio muito longo (~{est_sec:.1f}s). O limite é de {max_duration_sec:.0f} segundos."
            return True, est_sec, "OK"
        except Exception:
            return True, 0.0, "OK"

    if dur_sec > max_duration_sec:
        return False, dur_sec, f"Áudio possui {dur_sec:.1f} segundos. O limite máximo permitido é de {max_duration_sec:.0f} segundos."

    return True, dur_sec, "OK"


# ============================================================================
#  Workers
# ============================================================================

class PublicIpWorker(QThread):
    """Consulta IP público e operadora em background."""
    ip_info_ready = pyqtSignal(str, str)

    def run(self):
        ip, isp = query_current_network_origin(timeout_sec=3.5)
        self.ip_info_ready.emit(ip, isp)


class MonitorWorker(QThread):
    """Thread de monitoramento de um serviço específico."""
    result_ready = pyqtSignal(str, bool, float)

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


class DownOriginChecker(QThread):
    """Consulta IP e operadora no momento exato em que ocorre uma queda (DOWN)."""
    origin_resolved = pyqtSignal(str, str, str, float)

    def __init__(self, monitor_id: str, monitor_target: str, latency: float):
        super().__init__()
        self.monitor_id = monitor_id
        self.monitor_target = monitor_target
        self.latency = latency

    def run(self):
        ip, isp = query_current_network_origin(timeout_sec=2.5)
        self.origin_resolved.emit(self.monitor_id, ip, isp, self.latency)


# ============================================================================
#  Custom UI Components
# ============================================================================

class SparklineWidget(QWidget):
    """Gráfico de pulso e latência com tooltips de data e hora."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: List[Tuple[float, str]] = []
        self.points_cache: List[Tuple[float, float, float, str]] = []
        self.max_points = 24
        self.setFixedHeight(36)
        self.setMouseTracking(True)
        self.setToolTip("")

    def add_metric(self, is_up: bool, latency: float):
        val = latency if is_up else -1.0
        timestamp_str = datetime.now().strftime("%H:%M:%S")
        self.history.append((val, timestamp_str))
        if len(self.history) > self.max_points:
            self.history.pop(0)
        self.update()

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            help_event = e
            mouse_pos = help_event.pos()
            mx, my = mouse_pos.x(), mouse_pos.y()
            hit = None

            for pt_x, pt_y, val, ts in self.points_cache:
                dist = ((mx - pt_x) ** 2 + (my - pt_y) ** 2) ** 0.5
                if dist <= 7.0:
                    hit = (val, ts)
                    break

            if hit:
                val, ts = hit
                if val >= 0:
                    tip_text = f"🕒 {ts}\n⚡ Latência: {val:.1f} ms\nStatus: OK"
                else:
                    tip_text = f"🕒 {ts}\n⚠️ Pacote Perdido / DOWN"
                QToolTip.showText(help_event.globalPos(), tip_text, self)
            else:
                QToolTip.hideText()
            return True

        return super().event(e)

    def mouseMoveEvent(self, event: QMouseEvent):
        mouse_pos = event.position()
        mx, my = mouse_pos.x(), mouse_pos.y()
        hit = None

        for pt_x, pt_y, val, ts in self.points_cache:
            dist = ((mx - pt_x) ** 2 + (my - pt_y) ** 2) ** 0.5
            if dist <= 7.0:
                hit = (val, ts)
                break

        if hit:
            val, ts = hit
            if val >= 0:
                tip_text = f"🕒 {ts}\n⚡ Latência: {val:.1f} ms\nStatus: OK"
            else:
                tip_text = f"🕒 {ts}\n⚠️ Pacote Perdido / DOWN"
            QToolTip.showText(event.globalPosition().toPoint(), tip_text, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        painter.setBrush(QBrush(QColor(18, 22, 29, 180)))
        painter.setPen(QPen(QColor(255, 255, 255, 12), 1))
        painter.drawRoundedRect(0, 0, w, h, 4, 4)

        self.points_cache.clear()

        if not self.history:
            return

        valid_lats = [x[0] for x in self.history if x[0] >= 0]
        max_lat = max(valid_lats) if valid_lats else 100.0
        max_scale = max(max_lat * 1.2, 50.0)

        step_x = (w - 14) / max(1, self.max_points - 1)
        points = []

        for i, (val, ts) in enumerate(self.history):
            x = 7 + i * step_x
            if val < 0:
                y = h - 6
            else:
                ratio = min(val / max_scale, 1.0)
                y = (h - 8) - (ratio * (h - 16))
            points.append((x, y, val, ts))

        self.points_cache = list(points)

        if len(points) > 1:
            poly_path = QPainterPath()
            poly_path.moveTo(points[0][0], h - 3)
            for pt in points:
                poly_path.lineTo(pt[0], pt[1])
            poly_path.lineTo(points[-1][0], h - 3)
            poly_path.closeSubpath()

            fill_color = QColor(16, 185, 129, 40) if (self.history[-1][0] >= 0) else QColor(239, 68, 68, 40)
            painter.fillPath(poly_path, QBrush(fill_color))

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            if p2[2] < 0:
                line_pen = QPen(QColor(239, 68, 68, 210), 1.2, Qt.PenStyle.DashLine)
            else:
                line_pen = QPen(QColor(52, 211, 153, 220), 1.4)

            painter.setPen(line_pen)
            painter.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))

        for pt in points:
            x, y, val, _ = pt
            if val >= 0:
                p_border = QColor(16, 185, 129, 220)
                p_fill = QColor(52, 211, 153)
            else:
                p_border = QColor(220, 38, 38, 220)
                p_fill = QColor(248, 113, 113)

            painter.setPen(QPen(p_border, 1.0))
            painter.setBrush(QBrush(p_fill))
            painter.drawEllipse(QPoint(int(x), int(y)), 2, 2)

        if points:
            last = points[-1]
            pulse_ring = QColor(52, 211, 153, 90) if last[2] >= 0 else QColor(239, 68, 68, 90)
            painter.setPen(QPen(pulse_ring, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(int(last[0]), int(last[1])), 4, 4)


class StatusLed(QWidget):
    """LED indicador luminoso."""

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
            base_col = QColor(148, 163, 184)
            glow_col = QColor(148, 163, 184, 50)
        elif self.is_up:
            base_col = QColor(16, 185, 129)
            glow_col = QColor(16, 185, 129, 70)
        else:
            base_col = QColor(239, 68, 68)
            glow_col = QColor(239, 68, 68, 80)

        painter.setBrush(QBrush(glow_col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 12, 12)

        painter.setBrush(QBrush(base_col))
        painter.drawEllipse(3, 3, 8, 8)


class PublicNetworkBadge(QFrame):
    """Barra informativa de IP público e provedor (duplo clique atualiza)."""
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("IP e Provedor da sua conexão de internet.\nClique duplo para forçar atualização imediata.")
        self.setObjectName("publicNetworkBadge")
        self.setStyleSheet("""
            QFrame#publicNetworkBadge {
                background-color: rgba(30, 41, 59, 0.65);
                border: 1px solid rgba(56, 189, 248, 0.20);
                border-radius: 6px;
                padding: 2px;
            }
            QFrame#publicNetworkBadge:hover {
                background-color: rgba(30, 41, 59, 0.90);
                border: 1px solid rgba(56, 189, 248, 0.45);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.lbl_icon = QLabel("🌐")
        self.lbl_icon.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.lbl_icon)

        self.lbl_ip = QLabel("IP: Consultando…")
        self.lbl_ip.setStyleSheet("font-size: 10px; font-weight: 700; color: #38BDF8;")
        layout.addWidget(self.lbl_ip)

        self.lbl_sep = QLabel("•")
        self.lbl_sep.setStyleSheet("color: #475569; font-size: 10px;")
        layout.addWidget(self.lbl_sep)

        self.lbl_isp = QLabel("Operadora: …")
        self.lbl_isp.setStyleSheet("font-size: 10px; color: #94A3B8;")
        layout.addWidget(self.lbl_isp, 1)

    def set_loading(self):
        self.lbl_ip.setText("IP: Atualizando…")
        self.lbl_isp.setText("Operadora: …")
        self.lbl_ip.setStyleSheet("font-size: 10px; font-weight: 700; color: #FBBF24;")

    def update_info(self, ip: str, isp: str):
        display_isp = isp
        if len(display_isp) > 22:
            display_isp = display_isp[:20] + "…"

        self.lbl_ip.setText(f"IP: {ip}")
        self.lbl_isp.setText(f"{display_isp}")
        self.lbl_ip.setStyleSheet("font-size: 10px; font-weight: 700; color: #38BDF8;")
        self.lbl_isp.setStyleSheet("font-size: 10px; color: #CBD5E1;")

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.refresh_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class MonitorCard(QFrame):
    """Card de exibição do servidor/serviço."""
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

        self.sparkline = SparklineWidget(self)
        layout.addWidget(self.sparkline)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        child = self.childAt(event.position().toPoint())
        if child == self.sparkline:
            return
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
#  Modals & Dialogs
# ============================================================================

class EditServiceDialog(QDialog):
    """Modal de edição rápida de um serviço monitorado."""

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


class ServiceManagerDialog(QDialog):
    """Painel de configurações gerais (sons, transparência, adição e reordenação)."""

    def __init__(self, monitors: List[Dict[str, Any]], current_opacity: int,
                 up_sound: str, down_sound: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações & Painel - jacu.ia monitor")
        self.resize(600, 680)
        self.setModal(True)
        self.monitors = [dict(m) for m in monitors]
        self.opacity_val = current_opacity
        self.up_sound = up_sound
        self.down_sound = down_sound

        self.preview_player = QMediaPlayer()
        self.preview_audio_output = QAudioOutput()
        self.preview_player.setAudioOutput(self.preview_audio_output)
        self.preview_audio_output.setVolume(1.0)

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
        layout.setSpacing(10)

        # Transparência
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

        # Alertas de Som
        audio_group = QFrame()
        audio_group.setStyleSheet("background-color: #162032; border: 1px solid #1E293B; border-radius: 6px; padding: 6px;")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(8, 8, 8, 8)
        audio_layout.setSpacing(6)

        lbl_audio_title = QLabel("🔔 Alertas Sonoros (MP3 - Máximo 3 segundos):")
        lbl_audio_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #F59E0B;")
        audio_layout.addWidget(lbl_audio_title)

        row_up = QHBoxLayout()
        row_up.addWidget(QLabel("Som UP:"))
        self.txt_up_sound = QLineEdit(self.up_sound)
        self.txt_up_sound.setReadOnly(True)
        row_up.addWidget(self.txt_up_sound, 1)

        btn_browse_up = QPushButton("Procurar…")
        btn_browse_up.setStyleSheet("background-color: #334155; font-size: 11px;")
        btn_browse_up.clicked.connect(self.browse_up_sound)
        row_up.addWidget(btn_browse_up)

        btn_play_up = QPushButton("▶ Testar")
        btn_play_up.setStyleSheet("background-color: #059669; font-size: 11px;")
        btn_play_up.clicked.connect(lambda: self.preview_sound(self.txt_up_sound.text()))
        row_up.addWidget(btn_play_up)
        audio_layout.addLayout(row_up)

        row_down = QHBoxLayout()
        row_down.addWidget(QLabel("Som DOWN:"))
        self.txt_down_sound = QLineEdit(self.down_sound)
        self.txt_down_sound.setReadOnly(True)
        row_down.addWidget(self.txt_down_sound, 1)

        btn_browse_down = QPushButton("Procurar…")
        btn_browse_down.setStyleSheet("background-color: #334155; font-size: 11px;")
        btn_browse_down.clicked.connect(self.browse_down_sound)
        row_down.addWidget(btn_browse_down)

        btn_play_down = QPushButton("▶ Testar")
        btn_play_down.setStyleSheet("background-color: #DC2626; font-size: 11px;")
        btn_play_down.clicked.connect(lambda: self.preview_sound(self.txt_down_sound.text()))
        row_down.addWidget(btn_play_down)
        audio_layout.addLayout(row_down)

        layout.addWidget(audio_group)

        div1 = QFrame()
        div1.setFrameShape(QFrame.Shape.HLine)
        div1.setStyleSheet("color: #334155;")
        layout.addWidget(div1)

        # Adicionar novo serviço
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

        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet("color: #334155;")
        layout.addWidget(div2)

        # Ordem de Exibição
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

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_close = QPushButton("Salvar e Aplicar")
        self.btn_close.setStyleSheet("background-color: #10B981; padding: 8px 18px;")
        self.btn_close.clicked.connect(self.save_and_accept)
        btn_box.addWidget(self.btn_close)

        layout.addLayout(btn_box)

        self.refresh_list()

    def preview_sound(self, sound_path: str):
        if not sound_path or not os.path.exists(sound_path):
            QMessageBox.warning(self, "Aviso", f"Arquivo de áudio não encontrado:\n{sound_path}")
            return
        abs_path = os.path.abspath(sound_path)
        self.preview_player.stop()
        self.preview_player.setSource(QUrl.fromLocalFile(abs_path))
        self.preview_player.play()

    def browse_up_sound(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Selecionar Som para UP", "", "Arquivos MP3 (*.mp3)")
        if file_path:
            ok, dur, err_msg = validate_mp3_duration(file_path, MAX_SOUND_DURATION_SEC)
            if not ok:
                QMessageBox.critical(self, "Áudio Inválido", f"{err_msg}\nPor favor selecione um arquivo de até 3 segundos.")
                return
            self.txt_up_sound.setText(file_path)

    def browse_down_sound(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Selecionar Som para DOWN", "", "Arquivos MP3 (*.mp3)")
        if file_path:
            ok, dur, err_msg = validate_mp3_duration(file_path, MAX_SOUND_DURATION_SEC)
            if not ok:
                QMessageBox.critical(self, "Áudio Inválido", f"{err_msg}\nPor favor selecione um arquivo de até 3 segundos.")
                return
            self.txt_down_sound.setText(file_path)

    def on_opacity_change(self, val: int):
        self.opacity_val = val
        self.lbl_opacity_val.setText(f"{val}%")
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
            QMessageBox.warning(self, "Campos Obrigatórios", "Por favor, preencha o Nome e o Endereço IP / URL.")
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

    def save_and_accept(self):
        self.up_sound = self.txt_up_sound.text().strip()
        self.down_sound = self.txt_down_sound.text().strip()
        self.preview_player.stop()
        self.accept()

    def get_updated_monitors(self) -> List[Dict[str, Any]]:
        return self.monitors

    def get_updated_opacity(self) -> int:
        return self.opacity_val

    def get_updated_sounds(self) -> Tuple[str, str]:
        return self.up_sound, self.down_sound


# ============================================================================
#  Main Window
# ============================================================================

class JacuMonitorGadget(QMainWindow):
    """Janela principal do Gadget Always-on-Top."""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.monitors: List[Dict[str, Any]] = self.config.get("monitors", [])
        self.opacity_val: int = int(self.config.get("opacity", 92))
        self.sound_enabled: bool = bool(self.config.get("sound_enabled", True))
        self.up_sound: str = str(self.config.get("up_sound", DEFAULT_UP_SOUND))
        self.down_sound: str = str(self.config.get("down_sound", DEFAULT_DOWN_SOUND))
        self.window_geom = self.config.get("window", {"x": 100, "y": 100, "width": 350, "height": 500})

        self.workers: Dict[str, MonitorWorker] = {}
        self.cards: Dict[str, MonitorCard] = {}
        self.down_checkers: List[DownOriginChecker] = []
        self.is_always_on_top = True
        self.drag_position = QPoint()

        self.current_origin_ip = "Desconhecido"
        self.current_origin_isp = "Desconhecida"

        self.last_status: Dict[str, bool] = {}

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(1.0)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)

        self.ip_worker = None
        self.ip_timer = QTimer(self)

        self.init_window_properties()
        self.init_ui()
        self.init_ip_updater()
        self.start_monitoring()

    def init_window_properties(self):
        self.setWindowTitle(f"jacu.ia monitor ({APP_VERSION})")
        self.setMinimumSize(300, 220)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(self.opacity_val / 100.0)
        self.update_window_flags()
        self.restore_window_geometry()

    def restore_window_geometry(self):
        w = max(300, int(self.window_geom.get("width", 350)))
        h = max(220, int(self.window_geom.get("height", 500)))
        x = int(self.window_geom.get("x", 100))
        y = int(self.window_geom.get("y", 100))

        screens = QApplication.screens()
        is_visible = False
        for screen in screens:
            geom = screen.geometry()
            if geom.intersects(QRectF(x, y, min(w, 100), min(h, 100)).toRect()):
                is_visible = True
                break

        if is_visible:
            self.setGeometry(x, y, w, h)
        else:
            if screens:
                primary = screens[0].availableGeometry()
                fallback_x = primary.x() + (primary.width() - w) // 2
                fallback_y = primary.y() + (primary.height() - h) // 2
                self.setGeometry(fallback_x, fallback_y, w, h)
            else:
                self.resize(w, h)

    def save_window_geometry(self):
        pos = self.pos()
        sz = self.size()
        self.config["window"] = {
            "x": pos.x(),
            "y": pos.y(),
            "width": sz.width(),
            "height": sz.height()
        }
        self.config["sound_enabled"] = self.sound_enabled
        self.config["up_sound"] = self.up_sound
        self.config["down_sound"] = self.down_sound
        save_config(self.config)

    def update_window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow
        if self.is_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def init_ui(self):
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

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 6)
        self.central_container.setGraphicsEffect(shadow)

        self.setCentralWidget(self.central_container)

        root_layout = QVBoxLayout(self.central_container)
        root_layout.setContentsMargins(12, 10, 12, 6)
        root_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

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

        lbl_version = QLabel(APP_VERSION)
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

        self.btn_audio = QPushButton("🔊" if self.sound_enabled else "🔇")
        self.btn_audio.setToolTip("Ativar / Desativar Alertas Sonoros")
        self.btn_audio.setFixedSize(26, 26)
        self.btn_audio.setStyleSheet(self._get_audio_btn_style(self.sound_enabled))
        self.btn_audio.clicked.connect(self.toggle_sound)
        header.addWidget(self.btn_audio)

        self.btn_pin = QPushButton("📌")
        self.btn_pin.setToolTip("Fixar sobre outros programas (Always on Top)")
        self.btn_pin.setFixedSize(26, 26)
        self.btn_pin.setStyleSheet(self._get_pin_btn_style(self.is_always_on_top))
        self.btn_pin.clicked.connect(self.toggle_always_on_top)
        header.addWidget(self.btn_pin)

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

        self.network_badge = PublicNetworkBadge(self)
        self.network_badge.refresh_requested.connect(self.fetch_public_ip)
        root_layout.addWidget(self.network_badge)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(8)

        self.scroll_area.setWidget(self.cards_container)
        root_layout.addWidget(self.scroll_area, 1)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("Arrastar para redimensionar janela")
        footer_layout.addWidget(self.size_grip)
        root_layout.addLayout(footer_layout)

        self.rebuild_cards()

    def init_ip_updater(self):
        self.fetch_public_ip()
        self.ip_timer.setInterval(5 * 60 * 1000)
        self.ip_timer.timeout.connect(self.fetch_public_ip)
        self.ip_timer.start()

    def fetch_public_ip(self):
        if self.ip_worker and self.ip_worker.isRunning():
            return
        self.network_badge.set_loading()
        self.ip_worker = PublicIpWorker()
        self.ip_worker.ip_info_ready.connect(self.on_public_ip_received)
        self.ip_worker.start()

    def on_public_ip_received(self, ip: str, isp: str):
        self.current_origin_ip = ip
        self.current_origin_isp = isp
        self.network_badge.update_info(ip, isp)

    def _get_audio_btn_style(self, enabled: bool) -> str:
        if enabled:
            return """
                QPushButton {
                    background-color: rgba(16, 185, 129, 0.20);
                    color: #34D399;
                    border-radius: 5px;
                    font-size: 12px;
                    border: 1px solid rgba(16, 185, 129, 0.40);
                }
                QPushButton:hover {
                    background-color: rgba(16, 185, 129, 0.35);
                }
            """
        return """
            QPushButton {
                background-color: rgba(239, 68, 68, 0.20);
                color: #F87171;
                border-radius: 5px;
                font-size: 12px;
                border: 1px solid rgba(239, 68, 68, 0.40);
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.35);
            }
        """

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

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.btn_audio.setText("🔊" if self.sound_enabled else "🔇")
        self.btn_audio.setStyleSheet(self._get_audio_btn_style(self.sound_enabled))
        self.config["sound_enabled"] = self.sound_enabled
        save_config(self.config)

    def play_alert_sound(self, is_up: bool):
        if not self.sound_enabled:
            return

        sound_file = self.up_sound if is_up else self.down_sound
        if not os.path.isabs(sound_file):
            sound_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), sound_file)

        if os.path.exists(sound_file):
            self.media_player.stop()
            self.media_player.setSource(QUrl.fromLocalFile(os.path.abspath(sound_file)))
            self.media_player.play()

    def rebuild_cards(self):
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
        for idx, m in enumerate(self.monitors):
            if m.get("id") == monitor_id:
                diag = EditServiceDialog(m, self)
                if diag.exec() == QDialog.DialogCode.Accepted:
                    self.monitors[idx] = diag.get_data()
                    self.config["monitors"] = self.monitors
                    save_config(self.config)
                    if monitor_id in self.last_status:
                        del self.last_status[monitor_id]
                    self.rebuild_cards()
                    self.start_monitoring()
                break

    def start_monitoring(self):
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

        if self.ip_worker and self.ip_worker.isRunning():
            self.ip_worker.wait(1000)

        for chk in self.down_checkers:
            if chk.isRunning():
                chk.wait(500)
        self.down_checkers.clear()

    def on_metric_received(self, monitor_id: str, is_up: bool, latency: float):
        if monitor_id in self.cards:
            self.cards[monitor_id].update_status(is_up, latency)

        previous_status = self.last_status.get(monitor_id, None)

        if previous_status is None:
            self.last_status[monitor_id] = is_up
            for m in self.monitors:
                if m.get("id") == monitor_id:
                    append_service_log(
                        monitor_id=monitor_id,
                        monitor_target=f"{m.get('name')} ({m.get('target')})",
                        is_up=is_up,
                        latency=latency,
                        origin_ip=self.current_origin_ip,
                        origin_isp=self.current_origin_isp
                    )
                    break
            return

        if previous_status != is_up:
            self.last_status[monitor_id] = is_up
            self.play_alert_sound(is_up)

            target_name = ""
            for m in self.monitors:
                if m.get("id") == monitor_id:
                    target_name = f"{m.get('name')} ({m.get('target')})"
                    break

            if not is_up:
                checker = DownOriginChecker(monitor_id, target_name, latency)
                checker.origin_resolved.connect(self.on_down_origin_resolved)
                self.down_checkers.append(checker)
                checker.start()
            else:
                append_service_log(
                    monitor_id=monitor_id,
                    monitor_target=target_name,
                    is_up=True,
                    latency=latency,
                    origin_ip=self.current_origin_ip,
                    origin_isp=self.current_origin_isp
                )

    def on_down_origin_resolved(self, monitor_id: str, live_ip: str, live_isp: str, latency: float):
        self.current_origin_ip = live_ip
        self.current_origin_isp = live_isp
        self.network_badge.update_info(live_ip, live_isp)

        target_name = ""
        for m in self.monitors:
            if m.get("id") == monitor_id:
                target_name = f"{m.get('name')} ({m.get('target')})"
                break

        append_service_log(
            monitor_id=monitor_id,
            monitor_target=target_name,
            is_up=False,
            latency=latency,
            origin_ip=live_ip,
            origin_isp=live_isp
        )

    def toggle_always_on_top(self):
        self.is_always_on_top = not self.is_always_on_top
        self.btn_pin.setStyleSheet(self._get_pin_btn_style(self.is_always_on_top))
        self.update_window_flags()

    def open_manager(self):
        dialog = ServiceManagerDialog(
            monitors=self.monitors,
            current_opacity=self.opacity_val,
            up_sound=self.up_sound,
            down_sound=self.down_sound,
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.monitors = dialog.get_updated_monitors()
            self.opacity_val = dialog.get_updated_opacity()
            self.up_sound, self.down_sound = dialog.get_updated_sounds()
            self.setWindowOpacity(self.opacity_val / 100.0)

            self.config["monitors"] = self.monitors
            self.config["opacity"] = self.opacity_val
            self.config["up_sound"] = self.up_sound
            self.config["down_sound"] = self.down_sound
            save_config(self.config)

            self.last_status.clear()
            self.rebuild_cards()
            self.start_monitoring()
        else:
            self.setWindowOpacity(self.opacity_val / 100.0)

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
        self.save_window_geometry()
        self.stop_all_workers()
        QApplication.quit()

    def closeEvent(self, event):
        self.save_window_geometry()
        self.stop_all_workers()
        event.accept()
        QApplication.quit()


# ============================================================================
#  Main Entrypoint
# ============================================================================

def main():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    gadget = JacuMonitorGadget()
    gadget.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()