import argparse
import random
import socket
import time
import uuid
from protocol import send_json, recv_json
from discovery import send_discovery, elect_master


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


def discovery_loop() -> tuple:
    """Executa discovery com backoff exponencial até encontrar um master.
    Retorna (master_ip, master_port, master_name).
    """
    backoff = 2
    max_backoff = 30

    while True:
        print(f"[{WORKER_UUID}] [DISCOVERY] Enviando pacote UDP multicast...")
        responses = send_discovery(WORKER_UUID)

        if not responses:
            print(f"[{WORKER_UUID}] [DISCOVERY] NO_MASTER_FOUND. Aguardando {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue

        master = elect_master(responses)
        backoff = 2
        print(f"[{WORKER_UUID}] [ELECTION] Master eleito: {master['MASTER_NAME']} ({master['MASTER_IP']}:{master['MASTER_PORT']})")
        return master["MASTER_IP"], master["MASTER_PORT"], master["MASTER_NAME"]


def tcp_handshake(host: str, port: int, master_name: str):
    """Abre conexão TCP com o master eleito, envia ELECTION_ACK e aguarda resposta.
    Retorna o socket em caso de sucesso, None em caso de falha.
    """
    print(f"[{WORKER_UUID}] [CONNECTING] Conectando TCP a {host}:{port}...")
    try:
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(5)
        conn.connect((host, port))
        conn.settimeout(None)

        ack_payload = {
            "TYPE": "ELECTION_ACK",
            "WORKER_UUID": WORKER_UUID,
            "SELECTED_MASTER": master_name,
        }
        send_json(conn, ack_payload)

        response = recv_json(conn)
        if not response:
            print(f"[{WORKER_UUID}] [FALLBACK] Sem resposta ao ELECTION_ACK.")
            conn.close()
            return None

        if response.get("TYPE") == "ELECTION_ACK" and response.get("STATUS") == "ACCEPTED":
            print(f"[{WORKER_UUID}] [CONNECTING] ELECTION_ACK aceito por {master_name}. Iniciando Heartbeat.")
            return conn

        print(f"[{WORKER_UUID}] [FALLBACK] Resposta inesperada: {response}")
        conn.close()
        return None

    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"[{WORKER_UUID}] [FALLBACK] Falha TCP: {e}. Reiniciando discovery.")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--server-uuid", default=None)
    args = parser.parse_args()

    if args.host:
        # Modo legado: IP explícito, pula discovery
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
        return

    # Modo discovery
    while True:
        host, port, master_name = discovery_loop()
        conn = tcp_handshake(host, port, master_name)
        if conn is None:
            continue

        # Heartbeat loop (Sprint 1)
        try:
            while True:
                send_json(conn, {"SERVER_UUID": master_name, "TASK": "HEARTBEAT"})
                response = recv_json(conn)
                if not response:
                    print(f"[{WORKER_UUID}] [FALLBACK] Heartbeat sem resposta. Reiniciando discovery.")
                    break
                time.sleep(5)
        except Exception as e:
            print(f"[{WORKER_UUID}] [FALLBACK] Erro no Heartbeat: {e}. Reiniciando discovery.")
        finally:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
