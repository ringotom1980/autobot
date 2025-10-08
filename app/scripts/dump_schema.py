# app/scripts/dump_schema.py
from __future__ import annotations
import os, sys, time, socket, subprocess, shutil
import paramiko
from contextlib import contextmanager

# --------------------------------------------------------
# 讀取 .env
# --------------------------------------------------------
def load_env(path: str) -> dict:
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

# --------------------------------------------------------
# 尋找可用本機埠
# --------------------------------------------------------
def find_free_port(start=13306, end=13400) -> int:
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("找不到可用本機埠供 SSH 轉發使用")

# --------------------------------------------------------
# SSH 轉發 context manager
# --------------------------------------------------------
@contextmanager
def ssh_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, remote_host, remote_port, local_port):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    if ssh_key_path and os.path.isfile(ssh_key_path):
        try:
            pkey = paramiko.RSAKey.from_private_key_file(ssh_key_path)
        except Exception:
            pkey = paramiko.Ed25519Key.from_private_key_file(ssh_key_path)

    client.connect(
        hostname=ssh_host,
        port=int(ssh_port or 22),
        username=ssh_user,
        pkey=pkey,
        allow_agent=True,
        look_for_keys=True,
        timeout=15,
    )
    transport = client.get_transport()

    import threading, select

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", local_port))
    server.listen(5)

    stop_flag = {"stop": False}

    def handler(client_sock):
        try:
            chan = transport.open_channel("direct-tcpip", (remote_host, remote_port), client_sock.getsockname())
        except Exception:
            client_sock.close()
            return
        while True:
            r, _, _ = select.select([client_sock, chan], [], [], 1.0)
            if client_sock in r:
                data = client_sock.recv(16384)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(16384)
                if not data:
                    break
                client_sock.sendall(data)
        chan.close()
        client_sock.close()

    def loop():
        while not stop_flag["stop"]:
            r, _, _ = select.select([server], [], [], 1.0)
            if server in r:
                sock, _ = server.accept()
                threading.Thread(target=handler, args=(sock,), daemon=True).start()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop_flag["stop"] = True
        try:
            server.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

# --------------------------------------------------------
# 執行 mysqldump 匯出結構
# --------------------------------------------------------
def dump_schema(local_port, db_user, db_pass, db_name, out_path):
    if not shutil.which("mysqldump"):
        raise RuntimeError("找不到 mysqldump，請先安裝 MySQL 或 MariaDB Client。")

    args = [
        "mysqldump",
        "-h", "127.0.0.1",
        "-P", str(local_port),
        "-u", db_user,
        "--single-transaction",
        "--triggers",
        "--routines",
        "--events",
        "--no-data",                 # ★ 只匯出結構
        "--set-gtid-purged=OFF",
        db_name,
    ]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    env = os.environ.copy()
    env["MYSQL_PWD"] = db_pass

    with open(out_path, "wb") as f:
        proc = subprocess.run(args, env=env, stdout=f, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))

# --------------------------------------------------------
# 主流程
# --------------------------------------------------------
def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = load_env(os.path.join(root, ".env"))

    SSH_HOST = env.get("SSH_HOST", "")
    SSH_PORT = int(env.get("SSH_PORT", "22"))
    SSH_USER = env.get("SSH_USER", "")
    SSH_KEY  = env.get("SSH_KEY", env.get("SSH_KEY_PATH", ""))

    DB_HOST = env.get("DB_HOST", "srv1637.hstgr.io")
    DB_PORT = int(env.get("DB_PORT", "3306"))
    DB_NAME = env.get("DB_NAME", "")
    DB_USER = env.get("DB_USER", "")
    DB_PASS = env.get("DB_PASS", "")

    if not all([SSH_HOST, SSH_USER, DB_NAME, DB_USER, DB_PASS]):
        print("❌ 請先在 .env 設定 SSH_HOST/SSH_USER/SSH_KEY 及 DB_NAME/DB_USER/DB_PASS")
        sys.exit(1)

    local_port = find_free_port()
    schema_path = os.path.join(root, "schema_mysql.sql")

    print(f"→ 建立 SSH 轉發 {SSH_HOST}:{DB_HOST}:{DB_PORT} → 127.0.0.1:{local_port}")
    with ssh_tunnel(SSH_HOST, SSH_PORT, SSH_USER, SSH_KEY, DB_HOST, DB_PORT, local_port):
        print(f"→ 匯出結構到 {schema_path}")
        dump_schema(local_port, DB_USER, DB_PASS, DB_NAME, schema_path)
    print("✅ 匯出完成")

if __name__ == "__main__":
    main()
