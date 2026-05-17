
import socket
import threading
import json
import uuid
import queue
import time

HOST = "127.0.0.1"
PORT = 5000

CAPACITY = 5
RELEASE_THRESHOLD = 2

neighbors = {
    "MASTER_B": ("127.0.0.1", 5001)
}

workers = {}
borrowed_workers = {}
task_queue = queue.Queue()

lock = threading.Lock()


def log(message):
    print(f"[MASTER] {message}")


def send_json(conn, payload):
    conn.sendall((json.dumps(payload) + "\n").encode())


def receive_json(conn):
    data = ""

    while "\n" not in data:
        chunk = conn.recv(4096).decode()

        if not chunk:
            return None

        data += chunk

    return json.loads(data.strip())


def generate_tasks():
    counter = 0

    while True:
        time.sleep(2)

        task_queue.put(f"user_{counter}")

        counter += 1

        log(f"Tarefa adicionada. Fila={task_queue.qsize()}")


def monitor_load():

    while True:

        time.sleep(5)

        current_load = task_queue.qsize()

        if current_load > CAPACITY:

            log("SATURADO. Solicitando workers.")

            request_help(2)

        if current_load < RELEASE_THRESHOLD:

            release_borrowed_workers()


def request_help(workers_needed):

    for neighbor_id, address in neighbors.items():

        try:

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            sock.settimeout(5)

            sock.connect(address)

            request_id = str(uuid.uuid4())

            payload = {
                "type": "request_help",
                "request_id": request_id,
                "payload": {
                    "master_id": "MASTER_A",
                    "current_load": task_queue.qsize(),
                    "capacity": CAPACITY,
                    "workers_needed": workers_needed
                }
            }

            send_json(sock, payload)

            response = receive_json(sock)

            if not response:
                continue

            if response["type"] == "response_accepted":

                log("Ajuda aceita.")

                for worker in response["payload"]["worker_details"]:
                    log(f"Worker recebido: {worker['id']}")

            else:

                log("Ajuda recusada.")

            sock.close()

        except Exception as e:
            log(f"Erro request_help: {e}")


def release_borrowed_workers():

    with lock:

        for worker_id, conn in borrowed_workers.items():

            try:

                payload = {
                    "type": "command_release",
                    "request_id": str(uuid.uuid4()),
                    "payload": {
                        "original_master_address": "127.0.0.1:5001"
                    }
                }

                send_json(conn, payload)

                log(f"Worker liberado: {worker_id}")

            except Exception as e:
                log(e)


def process_worker(conn, message):

    if message["type"] == "register_temporary_worker":

        worker_id = message["payload"]["worker_id"]

        with lock:
            borrowed_workers[worker_id] = conn

        log(f"Worker temporário registrado: {worker_id}")

    while True:

        try:

            if task_queue.empty():

                send_json(conn, {
                    "TASK": "NO_TASK"
                })

            else:

                task = task_queue.get()

                send_json(conn, {
                    "TASK": "QUERY",
                    "USER": task
                })

            response = receive_json(conn)

            if response:

                log(f"STATUS recebido: {response}")

                send_json(conn, {
                    "STATUS": "ACK"
                })

            time.sleep(2)

        except Exception as e:

            log(e)

            break


def process_master(conn, message):

    if message["type"] == "request_help":

        request_id = message["request_id"]

        available_workers = list(workers.keys())

        if len(available_workers) == 0:

            response = {
                "type": "response_rejected",
                "request_id": request_id,
                "payload": {
                    "reason": "no_workers_available"
                }
            }

            send_json(conn, response)

            return

        selected = available_workers[:2]

        response = {
            "type": "response_accepted",
            "request_id": request_id,
            "payload": {
                "workers_offered": len(selected),
                "worker_details": []
            }
        }

        for wid in selected:

            response["payload"]["worker_details"].append({
                "id": wid,
                "address": "local"
            })

        send_json(conn, response)

        for wid in selected:

            worker_conn = workers[wid]

            redirect_payload = {
                "type": "command_redirect",
                "request_id": str(uuid.uuid4()),
                "payload": {
                    "new_master_address": "127.0.0.1:5000"
                }
            }

            send_json(worker_conn, redirect_payload)

            log(f"Worker {wid} redirecionado.")


def client_handler(conn):

    try:

        first_message = receive_json(conn)

        if not first_message:
            return

        if first_message.get("type") == "request_help":

            process_master(conn, first_message)

        elif first_message.get("type") == "register_temporary_worker":

            process_worker(conn, first_message)

        elif first_message.get("WORKER") == "ALIVE":

            worker_id = first_message["WORKER_UUID"]

            workers[worker_id] = conn

            log(f"Worker local conectado: {worker_id}")

            process_worker(conn, first_message)

    except Exception as e:
        log(e)


def server():

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server_socket.bind((HOST, PORT))

    server_socket.listen()

    log(f"Master ativo em {HOST}:{PORT}")

    threading.Thread(target=generate_tasks).start()

    threading.Thread(target=monitor_load).start()

    while True:

        conn, addr = server_socket.accept()

        thread = threading.Thread(
            target=client_handler,
            args=(conn,)
        )

        thread.start()


server()