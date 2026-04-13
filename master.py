import socket
import threading
import time
from protocol import send_json, recv_json

MASTER = {
    "UUID": "master-central",
    "HOST": "0.0.0.0",
    "PORT": 5001
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


if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()
    threading.Thread(target=distribute_jobs, daemon=True).start()
    threading.Thread(target=simulate_jobs, daemon=True).start()

    while True:
        time.sleep(10)
