import json
import socket
import time

DISCOVERY_PORT = 5000
MULTICAST_GROUP = "239.255.255.250"
DISCOVERY_TIMEOUT = 3.0
REQUIRED_REPLY_FIELDS = {"TYPE", "MASTER_NAME", "MASTER_IP", "MASTER_PORT", "STATUS"}


def send_discovery(worker_uuid: str) -> list:
    """Envia DISCOVERY via UDP multicast e coleta respostas por DISCOVERY_TIMEOUT segundos."""
    payload = json.dumps({"TYPE": "DISCOVERY", "WORKER_UUID": worker_uuid}) + "\n"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(DISCOVERY_TIMEOUT)

    responses = []
    deadline = time.time() + DISCOVERY_TIMEOUT

    try:
        sock.sendto(payload.encode("utf-8"), (MULTICAST_GROUP, DISCOVERY_PORT))

        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
                msg = json.loads(data.decode("utf-8").strip())
                missing = REQUIRED_REPLY_FIELDS - msg.keys()
                if missing:
                    print(f"[DISCOVERY] warning: reply sem campos {missing}, descartado")
                    continue
                if msg.get("TYPE") == "DISCOVERY_REPLY":
                    responses.append(msg)
            except socket.timeout:
                break
            except json.JSONDecodeError:
                print("[DISCOVERY] warning: payload inválido, descartado")
    finally:
        sock.close()

    return responses


def elect_master(responses: list) -> dict | None:
    """Elege o master com menor MASTER_NAME lexicográfico."""
    if not responses:
        return None
    return sorted(responses, key=lambda r: r["MASTER_NAME"])[0]
