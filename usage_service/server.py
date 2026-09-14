"""
Tiny local push server.

Protocol: newline-delimited JSON over a loopback TCP socket.

  * a client connects to 127.0.0.1:<port>
  * the server immediately sends the current snapshot (so a widget that was
    just started shows data at once)
  * every time the monitor collects new data, the snapshot is pushed to every
    connected client

Loopback-only and stdlib-only on purpose: no dependencies, nothing listening
on the network.  A WebSocket would need a handshake implementation for no
practical gain here.
"""

from __future__ import annotations

import json
import socket
import threading


class PushServer:
    def __init__(self, host="127.0.0.1", port=45654, on_command=None):
        self.host = host
        self.port = port
        # Called with a command name when a client asks for something.
        # Used by the widget's right-click "Refresh".
        self.on_command = on_command
        self._clients = set()
        self._lock = threading.Lock()
        self._snapshot = None
        self._sock = None
        self._thread = None
        self._stop = threading.Event()

    # ----------------------------------------------------------------
    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows: SO_REUSEADDR lets a second process take over a port
            # that is already being listened on, so two monitors would run
            # side by side.  This makes the second one fail to bind instead.
            self._sock.setsockopt(socket.SOL_SOCKET,
                                  socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        with self._lock:
            for client in list(self._clients):
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()

    # ----------------------------------------------------------------
    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                break  # socket closed during shutdown

            conn.settimeout(None)
            with self._lock:
                self._clients.add(conn)
                snapshot = self._snapshot

            # Give the newcomer whatever we already have.
            if snapshot is not None:
                self._send(conn, snapshot)

            threading.Thread(target=self._client_loop, args=(conn,),
                             daemon=True).start()

    def _client_loop(self, conn):
        """Read client commands, and notice the client going away."""
        buffer = b""
        try:
            while not self._stop.is_set():
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._handle_command(line)
        except OSError:
            pass
        finally:
            self._drop(conn)

    def _handle_command(self, line):
        line = line.strip()
        if not line or not self.on_command:
            return
        try:
            message = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            return
        command = message.get("command") if isinstance(message, dict) else None
        if command:
            try:
                self.on_command(command)
            except Exception:
                pass  # a bad command must never take the server down

    def _drop(self, conn):
        with self._lock:
            self._clients.discard(conn)
        try:
            conn.close()
        except OSError:
            pass

    def _send(self, conn, snapshot):
        try:
            payload = (json.dumps(snapshot, separators=(",", ":")) + "\n")
            conn.sendall(payload.encode("utf-8"))
            return True
        except OSError:
            self._drop(conn)
            return False

    # ----------------------------------------------------------------
    def broadcast(self, snapshot):
        """Remember this snapshot and push it to every connected client."""
        with self._lock:
            self._snapshot = snapshot
            clients = list(self._clients)
        for conn in clients:
            self._send(conn, snapshot)

    @property
    def client_count(self):
        with self._lock:
            return len(self._clients)
