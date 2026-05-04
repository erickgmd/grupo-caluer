# Sprint 2.1 — Descoberta Dinâmica e Eleição de Master pelos Workers

**Projeto:** P2P com Balanceamento de Carga Dinâmico  
**Prof.:** Michel Junio  
**Data:** 2026-05-04

---

## Objetivo

Workers iniciam sem IP/porta do Master configurados. Realizam descoberta via UDP, elegem deterministicamente o Master de menor nome lexicográfico, estabelecem conexão TCP e iniciam o ciclo de Heartbeat (Sprint 1).

---

## Escopo desta Sprint

Implementar as **Tarefas 01, 02 e 03** sem regressão no código existente:

- **T01** — Canal de Descoberta (UDP Multicast/Broadcast)
- **T02** — Lógica de Eleição Determinística
- **T03** — Transição UDP→TCP e Handshake Inicial
- **T04** — Resiliência e Reeleição (backoff + fallback)

---

## Arquitetura

### Arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `discovery.py` | Criar | Canal UDP: send multicast, receive unicast, election logic |
| `worker.py` | Modificar | Remover IP hardcoded; chamar discovery → election → TCP handshake |
| `master.py` | Modificar | Thread UDP listener; argumento `--name MASTER_X` |
| `protocol.py` | Não modificar | `send_json`/`recv_json` TCP — sem alterações |
| `protocol_master.py` | Não modificar | Mantido para compatibilidade |

### Compatibilidade com código existente

- `worker.py` mantém `--host` e `--port` como **override opcional**: se informados, pula o discovery e conecta diretamente (modo legado).
- `master.py` mantém `"master-central"` como UUID padrão se `--name` não for informado; os workers legados (sem discovery) continuam funcionando.
- Fluxo TCP existente (REGISTER_WORKER, JOB_RESULT, HEARTBEAT, NEW_JOB) **não é alterado**.

---

## Componentes

### `discovery.py`

Responsável por todo o canal UDP e pela lógica de eleição.

**Constantes:**
```python
DISCOVERY_PORT = 5000
MULTICAST_GROUP = "239.255.255.250"
DISCOVERY_TIMEOUT = 3.0  # segundos para coletar respostas
```

**Funções públicas:**

```python
def send_discovery(worker_uuid: str) -> list[dict]
```
Envia `DISCOVERY` via UDP multicast/broadcast, aguarda `DISCOVERY_TIMEOUT` segundos e retorna lista de respostas válidas (dicts com TYPE, MASTER_NAME, MASTER_IP, MASTER_PORT, STATUS).

```python
def elect_master(responses: list[dict]) -> dict | None
```
Aplica ordenação lexicográfica crescente em `MASTER_NAME`. Retorna o dict do master eleito ou `None` se lista vazia.

---

### Modificações em `master.py`

1. **Novo argumento CLI:** `--name` (ex: `MASTER_1`), default `"master-central"`.
2. **Nova thread:** `udp_listener()` — abre socket UDP na porta 5000, escuta multicast/broadcast, responde unicast ao Worker com:
   ```json
   {"TYPE":"DISCOVERY_REPLY","MASTER_NAME":"MASTER_1","MASTER_IP":"<ip>","MASTER_PORT":5001,"STATUS":"AVAILABLE"}
   ```
3. O `MASTER["UUID"]` passa a usar o valor de `--name` quando informado.

---

### Modificações em `worker.py`

Novo fluxo em `main()`:

```
se --host e --port foram informados explicitamente:
    → conectar diretamente (modo legado, sem discovery)
senão:
    loop com backoff exponencial:
        1. [DISCOVERY] send_discovery(WORKER_UUID) → responses
        2. se vazio → log NO_MASTER_FOUND, aguardar backoff, repetir
        3. [ELECTION]  elect_master(responses) → master
        4. [CONNECTING] TCP connect(master.ip, master.port) com timeout=5s
        5. se falhar → log FALLBACK, invalidar cache, repetir do passo 1
        6. enviar ELECTION_ACK, aguardar ACK do master
        7. iniciar loop de Heartbeat (Sprint 1)
```

---

## Payloads (exatamente como na spec)

Todos terminam em `\n`. Campos de controle em CAIXA ALTA.

**1. DISCOVERY (Worker → UDP Multicast)**
```json
{"TYPE": "DISCOVERY", "WORKER_UUID": "worker-abc12345"}
```

**2. DISCOVERY_REPLY (Master → Worker, UDP Unicast)**
```json
{"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "192.168.1.20", "MASTER_PORT": 5001, "STATUS": "AVAILABLE"}
```

**3. ELECTION_ACK — confirmação (Worker → Master, TCP)**
```json
{"TYPE": "ELECTION_ACK", "WORKER_UUID": "worker-abc12345", "SELECTED_MASTER": "MASTER_1"}
```

**4. ELECTION_ACK — resposta (Master → Worker, TCP)**
```json
{"TYPE": "ELECTION_ACK", "STATUS": "ACCEPTED", "MASTER_NAME": "MASTER_1"}
```

---

## Regra de Eleição

Ordenação lexicográfica crescente por `MASTER_NAME`. O primeiro da lista ordenada é eleito. Esta regra é idêntica em todos os Workers — garante consenso sem comunicação entre si.

Exemplos: `MASTER_1 < MASTER_2 < MASTER_10` (lexicográfico, não numérico).

---

## Resiliência

| Cenário | Comportamento |
|---|---|
| Nenhum master responde em 3s | Log `NO_MASTER_FOUND`, backoff exponencial (2s, 4s, 8s..., máx 30s), repete discovery |
| TCP falha após eleição | Log `FALLBACK`, invalida respostas coletadas, reinicia discovery imediatamente |
| Payload sem campos obrigatórios | Log warning, descarta resposta silenciosamente |
| Master eleito cai após conexão | Tratado pelo ciclo de Heartbeat (Sprint 1 já existente) |

**Logs esperados por etapa:**
- `[DISCOVERY]` — enviando pacote UDP
- `[ELECTION]` — master eleito
- `[CONNECTING]` — abrindo TCP
- `[FALLBACK]` — falha, reiniciando

---

## Cenários de Teste

| ID | Cenário | Critério de Sucesso |
|---|---|---|
| CT01 | Um único master disponível | Worker conecta ao MASTER_1 e inicia Heartbeat |
| CT02 | Múltiplos masters (MASTER_2, MASTER_1, MASTER_3) | Worker elege MASTER_1 (menor lexicográfico) |
| CT03 | Nenhum master responde | Worker loga NO_MASTER_FOUND, aplica backoff, repete |
| CT04 | TCP falha após eleição | Worker invalida cache, reinicia discovery |
| CT05 | Payload sem MASTER_PORT | Worker descarta resposta, loga warning |

---

## Restrições

1. `protocol.py` não pode ser modificado.
2. O fluxo TCP existente (REGISTER_WORKER, JOB_RESULT, HEARTBEAT) deve continuar funcionando sem alterações.
3. Workers legados com `--host`/`--port` explícitos devem continuar funcionando.
4. Strict parsing: campos obrigatórios ausentes → warning + descarte silencioso.
