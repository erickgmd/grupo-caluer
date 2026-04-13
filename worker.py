import argparse
import random
import socket
import time
import uuid
from protocol import send_json, recv_json


WORKER_UUID = f"worker-{uuid.uuid4().hex[:8]}"


def process_task(task):
    task_name = task.get("TASK")

    if task_name == "NO_TASK":
        print(f"[{WORKER_UUID}] Master informou que não há tarefas na fila.")
        return None

    if task_name != "QUERY":
        print(f"[{WORKER_UUID}] Tarefa inesperada: {task}")
        return {
            "STATUS": "NOK",
            "TASK": str(task_name),
            "WORKER_UUID": WORKER_UUID,
        }

    user_value = task.get("USER")
    print(f"[{WORKER_UUID}] Processando QUERY para USER={user_value}")

    time.sleep(random.randint(1, 3))

    success = random.choice([True, True, True, False])
    status = "OK" if success else "NOK"

    result = {
        "STATUS": status,
        "TASK": "QUERY",
        "WORKER_UUID": WORKER_UUID,
    }

    print(f"[{WORKER_UUID}] Processamento concluído: {result}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--server-uuid", default=None)
    args = parser.parse_args()

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((args.host, args.port))

    presentation_payload = {
        "WORKER": "ALIVE",
        "WORKER_UUID": WORKER_UUID,
    }

    if args.server_uuid:
        presentation_payload["SERVER_UUID"] = args.server_uuid

    print(f"[{WORKER_UUID}] Enviando apresentação: {presentation_payload}")
    send_json(conn, presentation_payload)

    task = recv_json(conn)
    if not task:
        print(f"[{WORKER_UUID}] Nenhuma resposta do Master.")
        conn.close()
        return

    print(f"[{WORKER_UUID}] Tarefa recebida: {task}")
    result = process_task(task)

    if result is None:
        conn.close()
        return

    send_json(conn, result)
    print(f"[{WORKER_UUID}] Status enviado ao Master.")

    ack = recv_json(conn)
    if ack and ack.get("STATUS") == "ACK":
        print(f"[{WORKER_UUID}] ACK final recebido do Master. Ciclo concluído.")
    else:
        print(f"[{WORKER_UUID}] ACK não recebido ou inválido: {ack}")

    conn.close()


if __name__ == "__main__":
    main()
