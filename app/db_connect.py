# app/db_connect.py
from __future__ import annotations
import socket
import select
import threading
import time
import logging
from contextlib import contextmanager
import paramiko

from .config import Config

log = logging.getLogger("autobot")

# 單例隧道
_tunnel = None
_tunnel_lock = threading.Lock()


class _ForwardServer:
    """在 127.0.0.1:<local_port> 接受連線，通過 Paramiko Transport 開 direct-tcpip 到遠端 DB。"""
    def __init__(self, transport: paramiko.Transport, local_port: int, remote_host: str, remote_port: int):
        self.transport = transport
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self._listen_sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.local_port))
        s.listen(100)
        self._listen_sock = s

        def _pipe(src, dst, name: str):
            """雙向資料管線；任一端關閉就安靜結束。"""
            try:
                while not self._stopping.is_set():
                    try:
                        r, _, _ = select.select([src], [], [], 60)
                    except Exception:
                        # src 端已經被系統關閉或 select 出錯
                        break
                    if src not in r:
                        continue
                    try:
                        data = src.recv(65536)
                    except OSError as e:
                        # 來源端不是 socket / 已關閉（WinError 10038 等）
                        log.debug("轉發[%s] recv 結束：%s", name, e)
                        break
                    if not data:
                        # 正常關閉
                        break
                    try:
                        # paramiko.Channel 只有 send；socket 有 send/sendall
                        if hasattr(dst, "sendall"):
                            dst.sendall(data)  # socket path
                        else:
                            # channel path：確保送完
                            sent = 0
                            while sent < len(data):
                                n = dst.send(data[sent:])  # type: ignore[attr-defined]
                                if n is None or n <= 0:
                                    raise OSError("channel send returned 0")
                                sent += n
                    except Exception as e:
                        log.debug("轉發[%s] send 結束：%s", name, e)
                        break
            finally:
                # 優雅雙向關閉；避免再拋例外
                for side in (dst, src):
                    try:
                        try:
                            side.shutdown(socket.SHUT_RDWR)  # socket 有；channel 沒有會丟例外
                        except Exception:
                            pass
                        side.close()
                    except Exception:
                        pass

        def _accept_loop():
            while not self._stopping.is_set():
                try:
                    client_sock, _ = s.accept()
                except OSError:
                    break
                # Windows 上降低延遲
                try:
                    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass

                # 若 transport 已失效就丟棄本次
                try:
                    if not (self.transport and self.transport.is_active()):
                        client_sock.close()
                        time.sleep(0.1)
                        continue
                except Exception:
                    try:
                        client_sock.close()
                    finally:
                        continue

                # 開 paramiko direct-tcpip 通道
                try:
                    chan = self.transport.open_channel(
                        kind="direct-tcpip",
                        dest_addr=(self.remote_host, self.remote_port),
                        src_addr=client_sock.getsockname()
                    )
                except Exception as e:
                    try:
                        client_sock.close()
                    finally:
                        log.warning("轉發開通遠端通道失敗：%s", e)
                    continue

                # 兩邊各跑一條線把資料互相轉
                t1 = threading.Thread(target=_pipe, args=(client_sock, chan, "c2s"), daemon=True, name="pf-c2s")
                t2 = threading.Thread(target=_pipe, args=(chan, client_sock, "s2c"), daemon=True, name="pf-s2c")
                t1.start(); t2.start()

        self._accept_thread = threading.Thread(target=_accept_loop, daemon=True, name="pf-accept")
        self._accept_thread.start()

    def stop(self):
        self._stopping.set()
        try:
            if self._listen_sock:
                self._listen_sock.close()
        except Exception:
            pass


class _ParamikoTunnel:
    def __init__(self,
                 ssh_host: str, ssh_port: int, ssh_user: str, ssh_pass: str,
                 local_port: int, remote_host: str, remote_port: int):
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port

        self.client: paramiko.SSHClient | None = None
        self.transport: paramiko.Transport | None = None
        self.forwarder: _ForwardServer | None = None
        self._running = False

    def start(self):
        if self._running and self.transport and self.transport.is_active():
            return

        # 1/3 建立 TCP + SSH
        log.info("⏳ 正在建立 SSH 隧道… (1/3 連線中)")

        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # 2/3 驗證
        log.info("🔑 驗證帳號密碼… (2/3 驗證中)")
        c.connect(
            hostname=self.ssh_host,
            port=self.ssh_port,
            username=self.ssh_user,
            password=self.ssh_pass,
            allow_agent=False,
            look_for_keys=False,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
        )
        log.info("Connected (version %s, client %s)", "2.0", "Paramiko")

        self.client = c
        self.transport = c.get_transport()
        if self.transport:
            # 開啟 TCP keepalive（每 30 秒）
            try:
                self.transport.set_keepalive(30)
            except Exception:
                pass

        # 3/3 啟動本機轉發
        self.forwarder = _ForwardServer(
            transport=self.transport,
            local_port=self.local_port,
            remote_host=self.remote_host,
            remote_port=self.remote_port
        )
        self.forwarder.start()

        # 等待本機埠 ready
        for _ in range(50):
            try:
                s = socket.create_connection(("127.0.0.1", self.local_port), timeout=0.2)
                s.close()
                break
            except Exception:
                time.sleep(0.1)

        self._running = True
        log.info("✅ 隧道已啟動，本機可用 127.0.0.1:%d 連線", self.local_port)

    def stop(self):
        try:
            if self.forwarder:
                self.forwarder.stop()
        except Exception:
            pass
        try:
            if self.transport:
                self.transport.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self._running = False


def _ensure_tunnel():
    global _tunnel
    with _tunnel_lock:
        if _tunnel:
            # 已存在但可能斷線，確保活著
            try:
                if _tunnel.transport and _tunnel.transport.is_active():
                    return
            except Exception:
                pass
        # 建立/重建
        if not Config.SSH_HOST or not Config.SSH_USER:
            raise RuntimeError("SSH 連線設定不足（請設 SSH_HOST / SSH_USER / SSH_PASS）")
        _tunnel = _ParamikoTunnel(
            ssh_host=Config.SSH_HOST,
            ssh_port=Config.SSH_PORT,
            ssh_user=Config.SSH_USER,
            ssh_pass=Config.SSH_PASS,
            local_port=Config.DB_PORT,   # 你的程式一律連 127.0.0.1:3307
            remote_host=Config.DB_HOST if Config.DB_HOST != "127.0.0.1" else "127.0.0.1",
            remote_port=3306             # 遠端 DB 真正埠
        )
        _tunnel.start()


class _DummyConn:
    """為了相容 main.py 的 get_connection().close()。"""
    def close(self):
        # 不做事：隧道保持常駐，由程式結束時釋放。
        pass


def get_connection():
    """
    與舊版介面相容：呼叫時啟動/確保隧道，回傳一個帶有 close() 的假物件。
    main.py 會立刻 close()，不影響隧道存活。
    """
    try:
        _ensure_tunnel()
    except Exception as e:
        log.exception("❌ SSH 隧道建立失敗：%s", e)
        raise
    # 這裡不建立 DB 連線（你的 .db.exec 自己會連 127.0.0.1:3307）
    return _DummyConn()


# 如果你想要 with 區塊控制，也提供：
@contextmanager
def ssh_mysql_tunnel():
    _ensure_tunnel()
    try:
        yield ("127.0.0.1", Config.DB_PORT)
    finally:
        # 常駐模式：不自動 stop；若要離開即關閉可改成 _tunnel.stop()
        pass
