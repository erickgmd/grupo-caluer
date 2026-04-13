import json

def send_json(conn, data):
    try:
        msg = json.dumps(data) + "\n"
        conn.sendall(msg.encode("utf-8"))
    except Exception as e:
        print(f"[ERRO send_json] {e}")

def recv_json(conn):
    buffer = ""

    while True:
        try:
            chunk = conn.recv(1024).decode("utf-8")
            if not chunk:
                return None

            buffer += chunk

            if "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
                    return json.loads(line)

        except Exception as e:
            print(f"[ERRO recv_json] {e}")
            return None