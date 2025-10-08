# app/scripts/dump_schema.py
from __future__ import annotations
import os, sys, socket, subprocess, shutil, paramiko
from contextlib import contextmanager

# ---------- UTF-8 ----------
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ---------- .env ----------
def load_env(path: str) -> dict:
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

# ---------- net utils ----------
def find_free_port(start=13306, end=13400) -> int:
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("找不到可用本機埠供 SSH 轉發使用")

# ---------- mysqldump ----------
def find_mysqldump(env: dict) -> str:
    p = env.get("MYSQLDUMP_PATH", "").strip()
    if p and os.path.isfile(p): return p
    p = shutil.which("mysqldump")
    if p: return p
    for c in [
        r"C:\Program Files\MariaDB 12.0\bin\mysqldump.exe",
        r"C:\Program Files\MariaDB 11.4\bin\mysqldump.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
        r"C:\xampp\mysql\bin\mysqldump.exe",
    ]:
        if os.path.isfile(c):
            return c
    return ""

def mysqldump_supports_set_gtid(mysqldump_path: str) -> bool:
    if not mysqldump_path: return False
    try:
        out = subprocess.check_output([mysqldump_path, "--version"], stderr=subprocess.STDOUT)
        return "mariadb" not in out.decode("utf-8", errors="ignore").lower()
    except Exception:
        return False

# ---------- SSH tunnel ----------
@contextmanager
def ssh_tunnel(ssh_host, ssh_port, ssh_user, ssh_pass,
               remote_host, remote_port, local_port):
    import threading, select
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    client.connect(
        hostname=ssh_host, port=int(ssh_port or 22), username=ssh_user, password=ssh_pass,
        allow_agent=False, look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15
    )
    transport = client.get_transport()
    if transport:
        try: transport.set_keepalive(30)
        except Exception: pass

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", local_port)); server.listen(100)

    stop_flag = {"stop": False}

    def handler(client_sock):
        try:
            chan = transport.open_channel("direct-tcpip", (remote_host, remote_port), client_sock.getsockname())
        except Exception:
            client_sock.close(); return
        import select as _select
        while True:
            r, _, _ = _select.select([client_sock, chan], [], [], 1.0)
            if client_sock in r:
                data = client_sock.recv(65536)
                if not data: break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(65536)
                if not data: break
                client_sock.sendall(data)
        try: chan.close()
        finally:
            try: client_sock.shutdown(socket.SHUT_RDWR)
            except Exception: pass
            client_sock.close()

    def accept_loop():
        import threading as _th, select as _select
        while not stop_flag["stop"]:
            try:
                r, _, _ = _select.select([server], [], [], 1.0)
                if server in r:
                    sock, _ = server.accept()
                    try: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except Exception: pass
                    _th.Thread(target=handler, args=(sock,), daemon=True).start()
            except OSError:
                break

    import threading
    t = threading.Thread(target=accept_loop, daemon=True); t.start()
    try:
        yield
    finally:
        stop_flag["stop"] = True
        try: server.close()
        except Exception: pass
        try: client.close()
        except Exception: pass

# ---------- dump ----------
def dump_schema(connect_host, connect_port, db_user, db_pass, db_name, out_path,
                mysqldump_path: str, supports_gtid: bool):
    if not mysqldump_path or not os.path.isfile(mysqldump_path):
        raise RuntimeError("找不到 mysqldump，請在 .env 設定 MYSQLDUMP_PATH 或安裝 MySQL/MariaDB Client。")

    args = [
        mysqldump_path,
        "-h", str(connect_host),
        "-P", str(connect_port),
        "-u", db_user,
        "--single-transaction",
        "--triggers",
        "--routines",
        "--events",
        "--no-data",
    ]
    if supports_gtid:
        args.append("--set-gtid-purged=OFF")
    args.append(db_name)

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    env = os.environ.copy()
    env["MYSQL_PWD"] = db_pass

    with open(out_path, "wb") as f:
        proc = subprocess.run(args, env=env, stdout=f, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))

# ---------- main ----------
def main():
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = load_env(os.path.join(ROOT, ".env"))

    # SSH
    SSH_HOST = env.get("SSH_HOST", "")
    SSH_PORT = int(env.get("SSH_PORT", "22"))
    SSH_USER = env.get("SSH_USER", "")
    SSH_PASS = env.get("SSH_PASS", "")

    # DB（你的專案：本機固定 3307，遠端真正 3306）
    DB_HOST = env.get("DB_HOST", "127.0.0.1")          # 遠端主機（可能是 127.0.0.1：代表 DB 跟 SSH 在同一台）
    DB_LOCAL_PORT = int(env.get("DB_PORT", "3307"))    # 本機給應用程式用；本腳本改用臨時埠避免衝突
    DB_REMOTE_PORT = int(env.get("DB_REMOTE_PORT", "3306"))  # ★ 新增：遠端 MySQL 真正埠
    DB_NAME = env.get("DB_NAME", "")
    DB_USER = env.get("DB_USER", "")
    DB_PASS = env.get("DB_PASS", "")

    if not all([SSH_HOST, SSH_USER, SSH_PASS, DB_NAME, DB_USER, DB_PASS]):
        print("❌ .env 參數不足（需要 SSH_HOST/SSH_USER/SSH_PASS 與 DB_NAME/DB_USER/DB_PASS）")
        sys.exit(1)

    schema_path = os.path.join(ROOT, "schema_mysql.sql")
    mysqldump_path = find_mysqldump(env)
    print(f"→ 使用 mysqldump：{mysqldump_path or '（未找到）'}")
    supports_gtid = mysqldump_supports_set_gtid(mysqldump_path)

    # 用臨時本機埠避免 3307 可能被你的主程式佔用
    local_port = find_free_port()
    print(f"→ 建立 SSH 轉發 {SSH_HOST}:{DB_HOST}:{DB_REMOTE_PORT} → 127.0.0.1:{local_port}")
    with ssh_tunnel(
        SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS,
        remote_host=DB_HOST, remote_port=DB_REMOTE_PORT, local_port=local_port
    ):
        print(f"→ 匯出結構到 {schema_path}")
        dump_schema("127.0.0.1", local_port, DB_USER, DB_PASS, DB_NAME, schema_path, mysqldump_path, supports_gtid)

    print("✅ 匯出完成")

if __name__ == "__main__":
    main()
