import socket
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8080
ROOT = Path(__file__).resolve().parent


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
    if path in ("/a", "/a.html"):
        return ROOT / "a.html"
    return ROOT / "index.html"


def handle(conn):
    try:
        conn.settimeout(1)
        req = recv_headers(conn)
        body = file_for(request_path(req)).read_bytes()
        conn.sendall(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html;charset=utf-8\r\n"
            b"Connection: close\r\n"
            b"\r\n" + body
        )
        conn.shutdown(socket.SHUT_WR)
    except TimeoutError:
        pass
    finally:
        conn.close()


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(8)
        server.settimeout(0.5)
        print(f"http://127.0.0.1:{PORT}/")
        try:
            while True:
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                handle(conn)
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
