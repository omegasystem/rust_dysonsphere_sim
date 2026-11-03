#!/usr/bin/env python3
"""
tcp_lockstep_protocol.py - Lockstep Tick-Sync TCP Channel (`127.0.0.1:18960`)
==============================================================================
Connects `rust_dysonsphere_sim` (Dynamic Simulator + 2.5D/3D PyQt GUI) with the
local AI inference engine (`rust_localsleep-moe` / `dyson_moe_bridge.py`).

Lockstep Rhythm Synchronization Rules:
  1. While the simulator advances ticks, every `sync_interval_ticks` (or immediately
     upon a critical grid/deadlock fault), the Simulator **automatically pauses**
     its physics tick timer (`PAUSED_WAITING_AI`).
  2. Simulator sends `tick_state_sync` (with generated state prompt + previous window's
     thermodynamic evaluation `LTM_CONSOLIDATED` / `ANTI_HEBBIAN_ROLLBACK`) over TCP.
  3. AI Inference Engine streams `ai_token_stream` chunks back to Simulator HUD and finishes
     with `ai_action_complete`.
  4. Simulator parses the AI's `<dyson_action>` JSON into dynamic system parameters, applies
     them to the Rust/Python simulation core, and **automatically resumes** the tick loop!
"""

import json
import queue
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional


DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 18960


class DysonTcpSyncServer:
    """Non-blocking background TCP Server embedded inside `rust_dysonsphere_sim`."""

    def __init__(
        self,
        host: str = DEFAULT_TCP_HOST,
        port: int = DEFAULT_TCP_PORT,
        on_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.on_event_callback = on_event_callback
        self._server_sock: Optional[socket.socket] = None
        self._client_sock: Optional[socket.socket] = None
        self._client_addr: Optional[tuple] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.inbound_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._client_sock:
                try:
                    self._client_sock.close()
                except Exception:
                    pass
                self._client_sock = None
            if self._server_sock:
                try:
                    self._server_sock.close()
                except Exception:
                    pass
                self._server_sock = None

    def is_client_connected(self) -> bool:
        with self._lock:
            return self._client_sock is not None

    def send_packet(self, payload: Dict[str, Any]) -> bool:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        data = line.encode("utf-8")
        with self._lock:
            if not self._client_sock:
                return False
            try:
                self._client_sock.sendall(data)
                return True
            except Exception:
                try:
                    self._client_sock.close()
                except Exception:
                    pass
                self._client_sock = None
                return False

    def _emit(self, evt: Dict[str, Any]) -> None:
        self.inbound_queue.put(evt)
        if self.on_event_callback:
            try:
                self.on_event_callback(evt)
            except Exception:
                pass

    def _accept_loop(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.settimeout(1.0)
        try:
            srv.bind((self.host, self.port))
            srv.listen(2)
            with self._lock:
                self._server_sock = srv
        except Exception as e:
            self._emit({"type": "server_error", "error": str(e)})
            return

        while self._running:
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except Exception:
                break

            conn.settimeout(1.0)
            with self._lock:
                if self._client_sock:
                    try:
                        self._client_sock.close()
                    except Exception:
                        pass
                self._client_sock = conn
                self._client_addr = addr

            self._emit({"type": "client_connected", "addr": f"{addr[0]}:{addr[1]}"})
            self._read_client_loop(conn, addr)

    def _read_client_loop(self, conn: socket.socket, addr: tuple) -> None:
        buf = b""
        while self._running:
            try:
                chunk = conn.recv(8192)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    line_str = raw_line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        msg = json.loads(line_str)
                        if isinstance(msg, dict):
                            self._emit(msg)
                    except Exception:
                        pass
            except socket.timeout:
                continue
            except Exception:
                break

        with self._lock:
            if self._client_sock is conn:
                self._client_sock = None
                self._client_addr = None
        try:
            conn.close()
        except Exception:
            pass
        self._emit({"type": "client_disconnected", "addr": f"{addr[0]}:{addr[1]}"})


class DysonTcpSyncClient:
    """Auto-reconnecting TCP Client used by the AI Inference Bridge to talk to `rust_dysonsphere_sim`."""

    def __init__(
        self,
        host: str = DEFAULT_TCP_HOST,
        port: int = DEFAULT_TCP_PORT,
        on_packet_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.on_packet_callback = on_packet_callback
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.inbound_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect_and_read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def is_connected(self) -> bool:
        with self._lock:
            return self._sock is not None

    def send_packet(self, payload: Dict[str, Any]) -> bool:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        data = line.encode("utf-8")
        with self._lock:
            if not self._sock:
                return False
            try:
                self._sock.sendall(data)
                return True
            except Exception:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
                return False

    def _emit(self, pkt: Dict[str, Any]) -> None:
        self.inbound_queue.put(pkt)
        if self.on_packet_callback:
            try:
                self.on_packet_callback(pkt)
            except Exception:
                pass

    def _connect_and_read_loop(self) -> None:
        while self._running:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            try:
                s.connect((self.host, self.port))
                s.settimeout(1.0)
                with self._lock:
                    self._sock = s
                self._emit({"type": "bridge_connected", "target": f"{self.host}:{self.port}"})
                self.send_packet({"type": "hello_ai_bridge", "agent": "rust_localsleep-moe"})
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
                time.sleep(1.5)
                continue

            buf = b""
            while self._running:
                try:
                    chunk = s.recv(16384)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        line_str = raw_line.decode("utf-8", errors="replace").strip()
                        if not line_str:
                            continue
                        try:
                            pkt = json.loads(line_str)
                            if isinstance(pkt, dict):
                                self._emit(pkt)
                        except Exception:
                            pass
                except socket.timeout:
                    continue
                except Exception:
                    break

            with self._lock:
                if self._sock is s:
                    self._sock = None
            try:
                s.close()
            except Exception:
                pass
            self._emit({"type": "bridge_disconnected", "target": f"{self.host}:{self.port}"})
            time.sleep(1.0)
