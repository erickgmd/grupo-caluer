import argparse
import json
import socket
import struct
import threading
import time
from protocol import send_json, recv_json

MASTER = {
    "UUID": "master-central",
    "NAME": "master-central",
    "HOST": "0.0.0.0",
    "PORT": 5001,
}

workers = {}       # worker_id -> socket
worker_info = {}   # worker_id -> {"HOST": str, "ELECTION_PORT": int}
job_queue = []

workers_lock = threading.Lock()
worker_info_lock = threading.Lock()
queue_lock = threading.Lock()

job_counter = 0


def broadcast_peer_list():
    with worker_info_lock:
        peer_list = [
            {"ID": wid, "HOST": info["HOST"], "ELECTION_PORT": info["ELECTION_PORT"]}
            for wid, info in worker_info.items()
        ]

    with workers_lock:
        conns = list(workers.values())

    for c in conns:
        try:
            send_json(c, {"TASK": "PEER_LIST", "PEERS": peer_list})
        except Exception as e:
            print(f"[{MASTER['UUID']}] Erro ao enviar PEER_LIST: {e}")


def remove_worker_by_conn(conn):
    remove_id = None

    with workers_lock:
        for worker_id, worker_conn in workers.items():
            if worker_conn == conn:
                remove_id = worker_id
                break
        if remove_id:
            del workers[remove_id]
            print(f"[{MASTER['UUID']}] Worker removido: {remove_id}")

    if remove_id:
        with worker_info_lock:
            worker_info.pop(remove_id, None)
        broadcast_peer_list()


def handle_client(conn, addr):
    print(f"[{MASTER['UUID']}] Nova conexão de {addr}")

    try:
        while True:
            data = recv_json(conn)
            if not data:
                break

            task = data.get("TASK")

            if task == "REGISTER_WORKER":
                worker_id = data["WORKER_UUID"]
                election_port = data.get("ELECTION_PORT")

                with workers_lock:
                    workers[worker_id] = conn

                with worker_info_lock:
                    worker_info[worker_id] = {
                        "HOST": addr[0],
                        "ELECTION_PORT": election_port
                    }

                print(f"[{MASTER['UUID']}] Worker registrado: {worker_id} ({addr[0]}:{election_port})")
                broadcast_peer_list()

            elif task == "JOB_RESULT":
                print(f"[{MASTER['UUID']}] Job concluído: {data['JOB_ID']} por {data['WORKER_UUID']}")

            elif task == "HEARTBEAT":
                send_json(conn, {"TASK": "HEARTBEAT", "RESPONSE": "ALIVE"})

            elif task == "NEW_JOB":
                with queue_lock:
                    job_queue.append(data)
                print(f"[{MASTER['UUID']}] Job externo recebido: {data['JOB_ID']}")

            elif data.get("TYPE") == "ELECTION_ACK":
                worker_id = data.get("WORKER_UUID", str(addr))
                selected = data.get("SELECTED_MASTER", MASTER["NAME"])
                print(f"[{MASTER['NAME']}] ELECTION_ACK de {worker_id} selecionou {selected}")
                send_json(conn, {
                    "TYPE": "ELECTION_ACK",
                    "STATUS": "ACCEPTED",
                    "MASTER_NAME": MASTER["NAME"],
                })

    except Exception as e:
        print(f"[{MASTER['UUID']}] Erro em handle_client: {e}")

    finally:
        remove_worker_by_conn(conn)
        try:
            conn.close()
        except:
            pass


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((MASTER["HOST"], MASTER["PORT"]))
    server.listen()

    print(f"[{MASTER['UUID']}] Escutando em {MASTER['HOST']}:{MASTER['PORT']}")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


def distribute_jobs():
    while True:
        try:
            with queue_lock:
                has_jobs = len(job_queue) > 0

            with workers_lock:
                has_workers = len(workers) > 0

            if has_jobs and has_workers:
                with queue_lock:
                    if not job_queue:
                        time.sleep(1)
                        continue
                    job = job_queue.pop(0)

                with workers_lock:
                    if not workers:
                        with queue_lock:
                            job_queue.insert(0, job)
                        time.sleep(1)
                        continue

                    worker_id, worker_conn = next(iter(workers.items()))

                print(f"[{MASTER['UUID']}] Enviando {job['JOB_ID']} para {worker_id}")
                send_json(worker_conn, job)

            time.sleep(1)

        except Exception as e:
            print(f"[{MASTER['UUID']}] Erro em distribute_jobs: {e}")
            time.sleep(1)


def simulate_jobs():
    global job_counter

    while True:
        try:
            job = {
                "TASK": "NEW_JOB",
                "JOB_ID": f"job-{job_counter}",
                "PAYLOAD": {"duration": 5}
            }

            with queue_lock:
                job_queue.append(job)

            print(f"[{MASTER['UUID']}] Novo job criado: {job['JOB_ID']}")
            job_counter += 1
            time.sleep(2)

        except Exception as e:
            print(f"[{MASTER['UUID']}] Erro em simulate_jobs: {e}")
            time.sleep(1)


def udp_listener():
    """Thread que escuta DISCOVERY via UDP multicast e responde unicast ao Worker."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    group = socket.inet_aton("239.255.255.250")
    mreq = struct.pack("4sL", group, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    sock.bind(("", 5000))
    print(f"[{MASTER['NAME']}] UDP listener ativo na porta 5000")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            msg = json.loads(data.decode("utf-8").strip())

            if msg.get("TYPE") != "DISCOVERY":
                continue

            # Determina o IP local que alcança o worker:
            # - loopback: retorna o próprio loopback
            # - rede real: usa roteamento via socket UDP
            if addr[0].startswith("127."):
                local_ip = "127.0.0.1"
            else:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.connect((addr[0], 1))
                    local_ip = probe.getsockname()[0]

            reply = json.dumps({
                "TYPE": "DISCOVERY_REPLY",
                "MASTER_NAME": MASTER["NAME"],
                "MASTER_IP": local_ip,
                "MASTER_PORT": MASTER["PORT"],
                "STATUS": "AVAILABLE",
            }) + "\n"

            sock.sendto(reply.encode("utf-8"), addr)
            print(f"[{MASTER['NAME']}] DISCOVERY_REPLY enviado para {addr}")
        except json.JSONDecodeError:
            print(f"[{MASTER['NAME']}] UDP: payload inválido, ignorado")
        except Exception as e:
            print(f"[{MASTER['NAME']}] Erro no UDP listener: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="master-central")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    MASTER["NAME"] = args.name
    MASTER["UUID"] = args.name
    MASTER["PORT"] = args.port
    MASTER["HOST"] = args.host

    threading.Thread(target=udp_listener, daemon=True).start()
    threading.Thread(target=start_server, daemon=True).start()
    threading.Thread(target=distribute_jobs, daemon=True).start()
    threading.Thread(target=simulate_jobs, daemon=True).start()

    while True:
        time.sleep(10)
