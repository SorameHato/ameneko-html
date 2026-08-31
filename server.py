import os
import ssl
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOST = "0.0.0.0"
PORT = 443
LISTEN_BACKLOG = 128
MAX_CONNECTIONS = 32
MAX_CONNECTIONS_PER_IP = 4
TLS_HANDSHAKE_TIMEOUT = 2
REQUEST_TIMEOUT = 1
ROOT = Path(__file__).resolve().parent
with ROOT.joinpath('domain.txt').open(encoding='utf-8') as f:
    DOMAIN = f.readline().strip()
CREDENTIALS_DIRECTORY = os.environ.get("CREDENTIALS_DIRECTORY")
if CREDENTIALS_DIRECTORY:
    CERT = Path(CREDENTIALS_DIRECTORY) / "fullchain.pem"
    KEY = Path(CREDENTIALS_DIRECTORY) / "privkey.pem"
else:
    CERT = Path(f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem")
    KEY = Path(f"/etc/letsencrypt/live/{DOMAIN}/privkey.pem")


class ConnectionLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.total = 0
        self.per_ip = {}

    def acquire(self, ip):
        with self.lock:
            count = self.per_ip.get(ip, 0)
            if self.total >= MAX_CONNECTIONS or count >= MAX_CONNECTIONS_PER_IP:
                return False
            self.total += 1
            self.per_ip[ip] = count + 1
            return True

    def release(self, ip):
        with self.lock:
            count = self.per_ip[ip]
            self.total -= 1
            if count == 1:
                del self.per_ip[ip]
            else:
                self.per_ip[ip] = count - 1


def recv_headers(conn):
    buf = b""
    while b"\r\n\r\n" not in buf and b"\n\n" not in buf:
        chunk = conn.recv(1024)
        if not chunk:
            break
        buf += chunk
        if len(buf) > 65536:
            break
    return buf


def request_path(req):
    parts = req.split(b"\r\n", 1)[0].split(b" ")
    if len(parts) < 2:
        return "/"
    return parts[1].decode("ascii", "replace").split("?", 1)[0]


def file_for(path):
    if path in ("/200B", "/200B.html", "/200b", "/200b.html"):
        return ROOT / "index.html"
    return ROOT / "a.html"


def handle(conn):
    try:
        conn.settimeout(REQUEST_TIMEOUT)
        req = recv_headers(conn)
        body = file_for(request_path(req)).read_bytes()
        conn.sendall(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html;charset=utf-8\r\n"
            b"Connection: close\r\n"
            b"\r\n" + body
        )
        conn.shutdown(socket.SHUT_WR)
    except (TimeoutError, ssl.SSLError, OSError):
        pass
    finally:
        conn.close()


def tls_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT, KEY)
    return ctx


def handshake(ctx, conn):
    conn.settimeout(TLS_HANDSHAKE_TIMEOUT)
    try:
        return ctx.wrap_socket(conn, server_side=True)
    except (ssl.SSLError, TimeoutError, OSError):
        return None


def serve_connection(ctx, conn, ip, limiter):
    try:
        tls = handshake(ctx, conn)
        if tls is not None:
            handle(tls)
    finally:
        conn.close()
        limiter.release(ip)


def main():
    if DOMAIN == "example.com":
        raise SystemExit("server.py의 DOMAIN을 실제 도메인으로 바꾸세요")
    ctx = tls_context()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(LISTEN_BACKLOG)
        server.settimeout(0.5)
        print(f"https://{DOMAIN}/")
        limiter = ConnectionLimiter()
        try:
            with ThreadPoolExecutor(
                max_workers=MAX_CONNECTIONS,
                thread_name_prefix="ameneko",
            ) as workers:
                while True:
                    try:
                        conn, address = server.accept()
                    except TimeoutError:
                        continue
                    ip = address[0]
                    if not limiter.acquire(ip):
                        conn.close()
                        continue
                    try:
                        workers.submit(serve_connection, ctx, conn, ip, limiter)
                    except RuntimeError:
                        conn.close()
                        limiter.release(ip)
                        raise
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
