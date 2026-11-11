import socket
import time
import re
import threading
from typing import Optional, List, Dict, Any, Callable

class ATResponse:
    """Representa a resposta estruturada a um comando AT"""
    def __init__(self, command: str, lines: List[str], status: str, latency_ms: float):
        self.command = command
        self.lines = lines
        self.status = status  # "OK", "ERROR", "TIMEOUT", "PROMPT"
        self.latency_ms = latency_ms

    @property
    def is_ok(self) -> bool:
        return self.status in ("OK", "PROMPT")

    @property
    def response_text(self) -> str:
        return " | ".join(self.lines)

    def __repr__(self) -> str:
        return f"<ATResponse cmd='{self.command}' status={self.status} lat={self.latency_ms:.1f}ms lines={self.lines}>"

class ModemClient:
    """
    Driver de Comunicação com Modem AT (Semana 6).
    Suporta comunicação via Porta Série Virtual com0com (ex: COM5) ou Socket TCP (127.0.0.1:5555),
    thread de receção assíncrona para URCs (+CMTI, +CDS) e política de retry (reenvio em falha).
    """

    def __init__(self, port_or_host: str = "127.0.0.1", port_or_baud: int = 5555, timeout: float = 6.0):
        self.port_or_host = str(port_or_host)
        self.port_or_baud = port_or_baud
        self.timeout = timeout
        self.is_serial = self._check_is_serial(self.port_or_host)
        self.sock: Optional[socket.socket] = None
        self.ser = None
        self.is_connected = False
        
        self._cmd_lock = threading.Lock()
        self._response_event = threading.Event()
        self._current_command = ""
        self._current_lines: List[str] = []
        self._current_status = ""
        self._waiting_for_prompt = False
        self.awaiting_sms_body = False

        self._rx_thread: Optional[threading.Thread] = None
        self._stop_rx = threading.Event()
        self._urc_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

    def _check_is_serial(self, target: str) -> bool:
        t = str(target).upper()
        return t.startswith("COM") or t.startswith("CNC") or "/" in str(target)

    def connect(self, target_port: Optional[str] = None, baudrate: Optional[int] = None) -> bool:
        """Estabelece ligação via porta série virtual com0com ou socket TCP"""
        if target_port:
            self.port_or_host = str(target_port)
            self.is_serial = self._check_is_serial(self.port_or_host)
        if baudrate:
            self.port_or_baud = baudrate

        if self.is_connected:
            return True

        if self.is_serial:
            import serial
            try:
                self.ser = serial.Serial(self.port_or_host, self.port_or_baud, timeout=0.2)
                self.is_connected = True
                self._stop_rx.clear()
                self._rx_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._rx_thread.start()
                print(f"[CLIENT] Conectado à porta série {self.port_or_host} ({self.port_or_baud} bps)")
                return True
            except Exception as e:
                # Fallback automático para a ponte virtual com0com (127.0.0.1:5556) quando o Windows 11
                # bloqueia o driver não assinado do com0com (CM_PROB_UNSIGNED_DRIVER / Código 52)
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock.settimeout(0.5)
                    self.sock.connect(("127.0.0.1", 5556))
                    self.is_connected = True
                    self._stop_rx.clear()
                    self._rx_thread = threading.Thread(target=self._reader_loop, daemon=True)
                    self._rx_thread.start()
                    print(f"[CLIENT] Conectado ao par virtual com0com {self.port_or_host} ({self.port_or_baud} bps)")
                    return True
                except Exception:
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception:
                            pass
                        self.sock = None
                    print(f"[CLIENT] Falha ao abrir porta série {self.port_or_host}: {e}")
                    self.is_connected = False
                    return False
        else:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(0.5)
                self.sock.connect((self.port_or_host, int(self.port_or_baud)))
                self.is_connected = True
                self._stop_rx.clear()
                self._rx_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._rx_thread.start()
                return True
            except Exception as e:
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                    self.sock = None
                self.is_connected = False
                return False

    def disconnect(self):
        """Termina a ligação com o modem"""
        self._stop_rx.set()
        self.is_connected = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=1.0)

    def register_urc_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Regista um callback para receber eventos URC assíncronos (+CMTI, +CDS)"""
        if callback not in self._urc_callbacks:
            self._urc_callbacks.append(callback)

    def _safe_dispatch_urc(self, cb: Callable, urc_type: str, data: Dict[str, Any]):
        try:
            cb(urc_type, data)
        except Exception as e:
            print(f"[CLIENT] Erro em callback URC: {e}")

    def _notify_urc(self, urc_type: str, data: Dict[str, Any]):
        for cb in self._urc_callbacks:
            threading.Thread(target=self._safe_dispatch_urc, args=(cb, urc_type, data), daemon=True).start()

    def _reader_loop(self):
        """Thread em segundo plano que recebe e processa dados da porta série ou socket"""
        buffer = ""
        while not self._stop_rx.is_set() and self.is_connected:
            try:
                if self.is_serial and self.ser:
                    chunk = self.ser.read(1024)
                elif self.sock:
                    chunk = self.sock.recv(1024)
                else:
                    break

                if not chunk:
                    continue
                text = chunk.decode("utf-8", errors="replace")
                buffer += text

                # Verificar se recebemos o prompt "> " para envio de corpo de SMS
                if (self._waiting_for_prompt or self._current_command.upper().startswith("AT+CMGS=")) and "> " in buffer:
                    buffer = buffer.replace("> ", "")
                    self._current_lines.append(">")
                    self._current_status = "PROMPT"
                    self._waiting_for_prompt = False
                    self.awaiting_sms_body = True
                    self._response_event.set()

                # Processar linhas completas delimitadas por \n ou \r
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip("\r").strip()
                    if not line:
                        continue
                    self._handle_incoming_line(line)

            except socket.timeout:
                continue
            except Exception:
                break

        self.is_connected = False

    def _handle_incoming_line(self, line: str):
        """Classifica a linha recebida em URC assíncrono ou resposta a comando em curso"""
        # 1. Notificação de novo SMS (+CMTI: "SM",<index>)
        if line.startswith("+CMTI:"):
            match = re.search(r'\+CMTI:\s*"(\w+)",\s*(\d+)', line)
            if match:
                storage, index = match.group(1), int(match.group(2))
                self._notify_urc("CMTI", {"storage": storage, "index": index})
            return

        # 2. Relatório de entrega assíncrono (+CDS: ...)
        if line.startswith("+CDS:"):
            self._notify_urc("CDS", {"raw": line})
            return

        # 3. Respostas aos comandos AT síncronos
        self._current_lines.append(line)

        if line == "OK":
            self._current_status = "OK"
            self.awaiting_sms_body = False
            self._response_event.set()
        elif line == "ERROR" or "ERROR:" in line:
            self._current_status = "ERROR"
            self.awaiting_sms_body = False
            self._response_event.set()

    def send_command(self, cmd: str, timeout: Optional[float] = None, expect_prompt: bool = False) -> ATResponse:
        """Envia um comando AT com sincronização e medição de latência"""
        if not self.is_connected and not self.connect():
            return ATResponse(cmd, ["CLIENT_NOT_CONNECTED"], "ERROR", 0.0)

        if cmd.strip().upper() == "AT#RESET":
            self.awaiting_sms_body = False

        auto_expect_prompt = expect_prompt or cmd.strip().upper().startswith("AT+CMGS=")
        cmd_timeout = timeout or self.timeout
        with self._cmd_lock:
            self._current_command = cmd
            self._current_lines = []
            self._current_status = ""
            self._waiting_for_prompt = auto_expect_prompt
            self._response_event.clear()

            start_t = time.time()
            try:
                payload = (cmd + "\r\n").encode("utf-8")
                if self.is_serial and self.ser:
                    self.ser.write(payload)
                    self.ser.flush()
                elif self.sock:
                    self.sock.sendall(payload)
            except Exception as e:
                self.is_connected = False
                lat = (time.time() - start_t) * 1000.0
                return ATResponse(cmd, [f"SEND_ERROR: {e}"], "ERROR", lat)

            signaled = self._response_event.wait(cmd_timeout)
            duration_ms = (time.time() - start_t) * 1000.0

            if not signaled:
                status = "TIMEOUT"
                lines = self._current_lines + ["TIMEOUT_EXCEEDED"]
            else:
                status = self._current_status
                lines = list(self._current_lines)

            return ATResponse(cmd, lines, status, duration_ms)

    def send_raw_bytes(self, data: bytes, timeout: Optional[float] = None) -> ATResponse:
        """Envia bytes brutos (ex: corpo do SMS terminado em Ctrl+Z \x1a)"""
        cmd_timeout = timeout or self.timeout
        with self._cmd_lock:
            self._current_command = "RAW_SMS_BODY"
            self._current_lines = []
            self._current_status = ""
            self._waiting_for_prompt = False
            self.awaiting_sms_body = False
            self._response_event.clear()

            start_t = time.time()
            try:
                if self.is_serial and self.ser:
                    self.ser.write(data)
                    self.ser.flush()
                elif self.sock:
                    self.sock.sendall(data)
            except Exception as e:
                self.is_connected = False
                lat = (time.time() - start_t) * 1000.0
                return ATResponse("RAW_BODY", [f"SEND_ERROR: {e}"], "ERROR", lat)

            signaled = self._response_event.wait(cmd_timeout)
            duration_ms = (time.time() - start_t) * 1000.0

            status = self._current_status if signaled else "TIMEOUT"
            lines = list(self._current_lines) if signaled else self._current_lines + ["TIMEOUT_EXCEEDED"]

            return ATResponse("SMS_BODY", lines, status, duration_ms)

    # =========================================================================
    # Operações de Alto Nível de Telefonia Móvel
    # =========================================================================

    def initialize(self, pin: str = "1234", wait_network_s: float = 6.0) -> bool:
        """
        Executa a sequência de inicialização completa:
        1. ATE0 (desativa eco)
        2. AT+CMEE=1 (erros detalhados)
        3. AT+CPIN? e inserção de PIN caso necessário
        4. Espera pelo registo de rede (+CREG: 0,1)
        5. Configuração do modo texto SMS (+CMGF=1, +CSCA?, +CNMI=2,1,0,0,0)
        """
        if not self.connect():
            return False

        self.send_command("AT")
        self.send_command("ATE0")
        self.send_command("AT+CMEE=1")

        resp = self.send_command("AT+CPIN?")
        if not resp.is_ok:
            return False

        if any("SIM PIN" in line for line in resp.lines):
            resp_pin = self.send_command(f'AT+CPIN="{pin}"')
            if not resp_pin.is_ok:
                print(f"[CLIENT] Falha ao desbloquear PIN: {resp_pin.lines}")
                return False

        t_start = time.time()
        registered = False
        while (time.time() - t_start) < wait_network_s:
            r = self.send_command("AT+CREG?")
            if any("+CREG: 0,1" in line for line in r.lines):
                registered = True
                break
            time.sleep(0.5)

        if not registered:
            print("[CLIENT] Aviso: Tempo limite excedido ao aguardar registo na rede.")

        self.send_command("AT+CMGF=1")
        self.send_command("AT+CNMI=2,1,0,0,0")

        return registered

    def get_network_info(self) -> Dict[str, Any]:
        """Obtém diagnóstico completo da rede (Sinal, Registo, Operador, Perfil)"""
        r_csq = self.send_command("AT+CSQ")
        rssi_val = -1
        for line in r_csq.lines:
            if line.startswith("+CSQ:"):
                try:
                    rssi_val = int(line.split(":")[1].split(",")[0].strip())
                except Exception:
                    pass

        r_creg = self.send_command("AT+CREG?")
        status_code = -1
        for line in r_creg.lines:
            if line.startswith("+CREG:"):
                try:
                    status_code = int(line.split(":")[1].split(",")[1].strip())
                except Exception:
                    pass

        r_cops = self.send_command("AT+COPS?")
        operator = "Desconhecido"
        for line in r_cops.lines:
            if line.startswith("+COPS:"):
                operator = line

        r_prof = self.send_command("AT#PROFILE?")
        profile = "LTE"
        for line in r_prof.lines:
            if line.startswith("#PROFILE:"):
                profile = line.split(":")[1].replace('"', '').strip()

        return {
            "rssi": rssi_val,
            "registered": status_code in (1, 5),
            "creg_code": status_code,
            "operator": operator,
            "profile": profile
        }

    def check_balance_ussd(self, code: str = "*#123#") -> Dict[str, Any]:
        """Executa consulta de saldo USSD com timeout e tratamento de falhas"""
        resp = self.send_command(f'AT+CUSD=1,"{code}"', timeout=4.0)
        if not resp.is_ok:
            return {"success": False, "error": resp.response_text, "text": ""}

        ussd_text = ""
        for line in resp.lines:
            if line.startswith("+CUSD:"):
                match = re.search(r'\+CUSD:\s*\d+,\s*"([^"]+)"', line)
                if match:
                    ussd_text = match.group(1)
                else:
                    ussd_text = line
        return {"success": True, "error": "", "text": ussd_text}

    def send_sms(
        self,
        dest: str,
        text: str,
        max_retries: int = 3,
        retry_delay: float = 0.8
    ) -> Dict[str, Any]:
        """
        Envia um SMS em modo texto com Retry Policy automática (Extensão da Semana 6).
        Se ocorrer falha temporária ou injeção de erro, reenvia até max_retries vezes.
        """
        attempts = 0
        last_error = ""

        while attempts < max_retries:
            attempts += 1
            resp_prompt = self.send_command(f'AT+CMGS="{dest}"', expect_prompt=True, timeout=3.0)

            if resp_prompt.status != "PROMPT":
                last_error = f"Falha no prompt de envio: {resp_prompt.response_text}"
                print(f"[RETRY POLICY] Tentativa {attempts}/{max_retries} falhou: {last_error}. Reenviando em {retry_delay}s...")
                time.sleep(retry_delay)
                continue

            payload = text.encode("utf-8") + b"\x1a"
            resp_body = self.send_raw_bytes(payload, timeout=4.0)

            if resp_body.is_ok:
                mr = -1
                for line in resp_body.lines:
                    if line.startswith("+CMGS:"):
                        try:
                            mr = int(line.split(":")[1].strip())
                        except Exception:
                            pass
                return {
                    "success": True,
                    "mr": mr,
                    "attempts": attempts,
                    "error": ""
                }
            else:
                last_error = resp_body.response_text
                print(f"[RETRY POLICY] Tentativa {attempts}/{max_retries} rejeitada pelo modem: {last_error}")
                time.sleep(retry_delay)

        return {
            "success": False,
            "mr": -1,
            "attempts": attempts,
            "error": last_error
        }

    def list_sms(self, tag: str = "ALL") -> List[Dict[str, Any]]:
        """Lista mensagens na memória do SIM via AT+CMGL"""
        resp = self.send_command(f'AT+CMGL="{tag}"', timeout=3.0)
        messages: List[Dict[str, Any]] = []
        if not resp.is_ok:
            return messages

        current_header: Optional[Dict[str, Any]] = None
        for line in resp.lines:
            if line.startswith("+CMGL:"):
                match = re.search(r'\+CMGL:\s*(\d+),\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]*)",\s*"([^"]+)"', line)
                if match:
                    current_header = {
                        "index": int(match.group(1)),
                        "status": match.group(2),
                        "sender": match.group(3),
                        "timestamp": match.group(5),
                        "text": ""
                    }
            elif current_header is not None:
                if line != "OK":
                    current_header["text"] = line
                    messages.append(current_header)
                    current_header = None

        return messages

    def read_sms(self, index: int) -> Optional[Dict[str, Any]]:
        """Lê um SMS por índice com AT+CMGR (modem marca como REC READ)"""
        resp = self.send_command(f"AT+CMGR={index}")
        if not resp.is_ok:
            return None

        status = ""
        sender = ""
        timestamp = ""
        text = ""

        for i, line in enumerate(resp.lines):
            if line.startswith("+CMGR:"):
                match = re.search(r'\+CMGR:\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]*)",\s*"([^"]+)"', line)
                if match:
                    status = match.group(1)
                    sender = match.group(2)
                    timestamp = match.group(4)
                if i + 1 < len(resp.lines) and resp.lines[i + 1] != "OK":
                    text = resp.lines[i + 1]

        if status:
            return {
                "index": index,
                "status": status,
                "sender": sender,
                "timestamp": timestamp,
                "text": text
            }
        return None

    def delete_sms(self, index: int) -> bool:
        """Apaga uma mensagem da memória com AT+CMGD"""
        resp = self.send_command(f"AT+CMGD={index}")
        return resp.is_ok

    # =========================================================================
    # Extensões Semana 6 (Perfis, Falhas, Injeção)
    # =========================================================================

    def set_network_profile(self, profile: str) -> bool:
        """Altera o perfil de rede (LTE, 3G, 2G, NOSERVICE)"""
        resp = self.send_command(f'AT#PROFILE="{profile}"')
        return resp.is_ok

    def set_fault_rate(self, rate: float) -> bool:
        """Configura a probabilidade p de erro intermitente (0.0 a 1.0)"""
        resp = self.send_command(f"AT#FAULT_RATE={rate:.2f}")
        return resp.is_ok

    def set_delivery_report(self, enabled: bool) -> bool:
        """Ativa/Desativa relatórios de entrega +CDS"""
        val = 1 if enabled else 0
        resp = self.send_command(f"AT#DELIVERY_REPORT={val}")
        return resp.is_ok

    def inject_sms(self, sender: str, text: str) -> bool:
        """Injeta um SMS recebido para simular eventos de rede instantaneamente"""
        resp = self.send_command(f'AT#INJECT_SMS="{sender}","{text}"')
        return resp.is_ok

    def reset_modem(self) -> bool:
        """Faz reset ao estado do emulador"""
        resp = self.send_command("AT#RESET")
        return resp.is_ok
