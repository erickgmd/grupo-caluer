# Sprint 2.1 — Discovery & Election Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar descoberta dinâmica UDP e eleição determinística de Master ao Worker, sem regressão no fluxo TCP existente.

**Architecture:** Novo módulo `discovery.py` encapsula o canal UDP e a lógica de eleição. `master.py` ganha uma thread UDP listener e argumento `--name`. `worker.py` troca IP hardcoded pelo fluxo discovery → election → TCP handshake, mantendo `--host`/`--port` como override legado.

**Tech Stack:** Python 3, stdlib apenas (socket, threading, json, argparse, uuid, time)

---

## Task 1: Criar `discovery.py` — Canal UDP e Eleição

**Files:**
- Create: `discovery.py`

- [ ] **Step 1: Criar o arquivo com constantes e imports**

```python
# discovery.py
import json
import socket
import time

DISCOVERY_PORT = 5000
MULTICAST_GROUP = "239.255.255.250"
DISCOVERY_TIMEOUT = 3.0
REQUIRED_REPLY_FIELDS = {"TYPE", "MASTER_NAME", "MASTER_IP", "MASTER_PORT", "STATUS"}
```

- [ ] **Step 2: Implementar `send_discovery`**

```python
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
```

- [ ] **Step 3: Implementar `elect_master`**

```python
def elect_master(responses: list) -> dict | None:
    """Elege o master com menor MASTER_NAME lexicográfico."""
    if not responses:
        return None
    return sorted(responses, key=lambda r: r["MASTER_NAME"])[0]
```

- [ ] **Step 4: Verificar manualmente que o arquivo está correto**

Ler `discovery.py` e confirmar que os três blocos acima estão presentes sem erros de sintaxe:
```bash
python -c "import discovery; print('OK')"
```
Esperado: `OK`

- [ ] **Step 5: Commit**

```bash
git add discovery.py
git commit -m "feat: add discovery.py — UDP multicast channel and deterministic election"
```

---

## Task 2: Modificar `master.py` — Argumento `--name` e Thread UDP

**Files:**
- Modify: `master.py`

- [ ] **Step 1: Adicionar imports necessários**

No topo de `master.py`, após os imports existentes, acrescentar:
```python
import argparse
import struct
```

Os imports `socket`, `threading`, `time` já existem — não duplicar.

- [ ] **Step 2: Adicionar parsing de argumentos CLI**

Substituir o bloco `MASTER = {...}` e o bloco `if __name__ == "__main__":` para aceitar `--name` e `--port`.

Localizar o bloco atual no final do arquivo:
```python
if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()
    threading.Thread(target=distribute_jobs, daemon=True).start()
    threading.Thread(target=simulate_jobs, daemon=True).start()

    while True:
        time.sleep(10)
```

Substituir **todo** o arquivo apenas na parte do `MASTER` dict e `__main__`, mantendo todas as funções existentes intactas.

No topo, a linha:
```python
MASTER = {
    "UUID": "master-central",
    "HOST": "0.0.0.0",
    "PORT": 5001
}
```
Passa a ser inicializada em `__main__` e exposta como variável global. Trocar por:

```python
MASTER = {
    "UUID": "master-central",
    "HOST": "0.0.0.0",
    "PORT": 5001,
    "NAME": "master-central",
}
```

- [ ] **Step 3: Implementar `udp_listener()`**

Adicionar esta função antes do bloco `if __name__ == "__main__":`:

```python
def udp_listener():
    """Thread que escuta DISCOVERY via UDP e responde unicast ao Worker."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Habilitar recebimento multicast
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

            reply = json.dumps({
                "TYPE": "DISCOVERY_REPLY",
                "MASTER_NAME": MASTER["NAME"],
                "MASTER_IP": addr[1] if MASTER["HOST"] == "0.0.0.0" else MASTER["HOST"],
                "MASTER_PORT": MASTER["PORT"],
                "STATUS": "AVAILABLE",
            }) + "\n"

            # Descobrir IP local para incluir na resposta
            local_ip = socket.gethostbyname(socket.gethostname())
            reply_dict = json.loads(reply.strip())
            reply_dict["MASTER_IP"] = local_ip
            sock.sendto((json.dumps(reply_dict) + "\n").encode("utf-8"), addr)

            print(f"[{MASTER['NAME']}] DISCOVERY_REPLY enviado para {addr}")
        except Exception as e:
            print(f"[{MASTER['NAME']}] Erro no UDP listener: {e}")
```

- [ ] **Step 4: Atualizar `__main__` para parsear args e iniciar UDP thread**

Substituir o bloco `if __name__ == "__main__":` existente por:

```python
if __name__ == "__main__":
    import json as _json  # já importado, mas necessário para udp_listener
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
```

- [ ] **Step 5: Verificar que master ainda sobe sem erros**

```bash
python master.py --name MASTER_1 &
sleep 2
kill %1
```
Esperado: linha `[MASTER_1] Escutando em 0.0.0.0:5001` e `[MASTER_1] UDP listener ativo na porta 5000` nos logs.

- [ ] **Step 6: Verificar retrocompatibilidade — sem `--name` usa "master-central"**

```bash
python master.py &
sleep 2
kill %1
```
Esperado: `[master-central] Escutando em 0.0.0.0:5001`

- [ ] **Step 7: Commit**

```bash
git add master.py
git commit -m "feat: add UDP discovery listener and --name arg to master"
```

---

## Task 3: Modificar `worker.py` — Substituir IP Hardcoded pelo Fluxo Discovery

**Files:**
- Modify: `worker.py`

- [ ] **Step 1: Adicionar import de discovery no topo de `worker.py`**

Após os imports existentes, adicionar:
```python
from discovery import send_discovery, elect_master
```

- [ ] **Step 2: Adicionar função `discovery_loop`**

Adicionar antes de `main()`:

```python
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
        backoff = 2  # reset após sucesso
        print(f"[{WORKER_UUID}] [ELECTION] Master eleito: {master['MASTER_NAME']} ({master['MASTER_IP']}:{master['MASTER_PORT']})")
        return master["MASTER_IP"], master["MASTER_PORT"], master["MASTER_NAME"]
```

- [ ] **Step 3: Adicionar função `tcp_handshake`**

Adicionar após `discovery_loop()`:

```python
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
```

- [ ] **Step 4: Atualizar `main()` para usar discovery quando `--host` não for explicitado**

Substituir o conteúdo de `main()` pelo seguinte (mantendo `process_task` intacto):

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--server-uuid", default=None)
    args = parser.parse_args()

    if args.host:
        # Modo legado: IP explícito, pula discovery
        host, port = args.host, args.port
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.connect((host, port))
        presentation_payload = {"WORKER": "ALIVE", "WORKER_UUID": WORKER_UUID}
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
        ack = recv_json(conn)
        if ack and ack.get("STATUS") == "ACK":
            print(f"[{WORKER_UUID}] ACK final recebido.")
        conn.close()
        return

    # Modo discovery
    while True:
        host, port, master_name = discovery_loop()
        conn = tcp_handshake(host, port, master_name)
        if conn is None:
            continue  # fallback: reinicia discovery

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
```

- [ ] **Step 5: Verificar que worker no modo legado ainda funciona**

Com `master.py` rodando:
```bash
python master.py --name MASTER_1 &
python worker.py --host 127.0.0.1 --port 5001
```
Esperado: Worker conecta, envia apresentação, recebe tarefa, fecha.

- [ ] **Step 6: Verificar que worker no modo discovery funciona**

```bash
python master.py --name MASTER_1 &
sleep 1
python worker.py
```
Esperado nos logs do worker:
```
[DISCOVERY] Enviando pacote UDP multicast...
[ELECTION] Master eleito: MASTER_1 (...)
[CONNECTING] Conectando TCP a ...:5001...
[CONNECTING] ELECTION_ACK aceito por MASTER_1. Iniciando Heartbeat.
```

- [ ] **Step 7: Verificar que master responde ELECTION_ACK via TCP**

O `handle_client` atual em `master.py` não trata `ELECTION_ACK`. Verificar se a mensagem passa sem travar — como o loop do master faz `while True: data = recv_json(conn)`, ele vai ignorar o `TYPE` desconhecido e aguardar próxima mensagem (Heartbeat). O Worker não espera resposta do master ao `ELECTION_ACK` no fluxo legado; **mas no novo fluxo sim**.

Adicionar tratamento de `ELECTION_ACK` em `handle_client` dentro de `master.py`:

Localizar o bloco `elif task == "NEW_JOB":` e adicionar antes do `except`:

```python
            elif data.get("TYPE") == "ELECTION_ACK":
                worker_id = data.get("WORKER_UUID", str(addr))
                selected = data.get("SELECTED_MASTER", MASTER["NAME"])
                print(f"[{MASTER['NAME']}] ELECTION_ACK de {worker_id} selecionou {selected}")
                send_json(conn, {
                    "TYPE": "ELECTION_ACK",
                    "STATUS": "ACCEPTED",
                    "MASTER_NAME": MASTER["NAME"],
                })
```

- [ ] **Step 8: Novo teste end-to-end do fluxo completo**

```bash
python master.py --name MASTER_1 &
sleep 1
python worker.py
```
Esperado: Worker recebe `ELECTION_ACK STATUS=ACCEPTED` e inicia Heartbeat loop.

- [ ] **Step 9: Commit final**

```bash
git add worker.py master.py
git commit -m "feat: worker discovery flow — UDP multicast, election, TCP handshake"
```

---

## Checklist de Regressão

Antes de considerar a sprint concluída:

- [ ] `python master.py` (sem args) sobe com UUID "master-central" e escuta TCP + UDP
- [ ] `python worker.py --host 127.0.0.1 --port 5001` funciona igual ao Sprint 1
- [ ] `python worker.py` (sem args) executa discovery → election → TCP → Heartbeat
- [ ] Dois masters (`MASTER_1` e `MASTER_2`) na rede → worker elege `MASTER_1`
- [ ] Nenhum master na rede → worker loga `NO_MASTER_FOUND` e aplica backoff

---

## Cenários de Teste Manuais (CT)

| CT | Como executar | Critério |
|---|---|---|
| CT01 | `master.py --name MASTER_1` + `worker.py` | Conecta a MASTER_1, Heartbeat ativo |
| CT02 | `master.py --name MASTER_1` + `master.py --name MASTER_2 --port 5002` + `worker.py` | Elege MASTER_1 |
| CT03 | `worker.py` sem nenhum master | Log NO_MASTER_FOUND, backoff 2→4→8→... |
| CT04 | Matar master após worker conectar | Worker loga FALLBACK, reinicia discovery |
| CT05 | Master responde sem MASTER_PORT | Worker loga warning, descarta, continua |
