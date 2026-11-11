import socket
import time
import random
import threading
from datetime import datetime
from enum import Enum
from typing import Optional, List

from telemetry_logger import default_telemetry

HOST = "127.0.0.1"
PORT = 5555

# 1. Estados da Máquina de Estados (Semanas 1-7)
class ModemState(Enum):
    BOOT = 0
    PIN_REQUIRED = 1
    SIM_PUK = 2              # Bloqueado após 3 tentativas falhadas de PIN
    SIM_READY = 3
    REGISTRATION = 4         # Busca de rede (CREG: 0,2)
    SMS_STACK_USSD = 5       # Registado na rede e stack pronta (CREG: 0,1)

# 2. Tabela de Latências Configuráveis (Protocolo RSCM)
LATENCY_TABLE = {
    "AT": (0.02, 0.05),        # 20 - 50 ms
    "ATE0": (0.01, 0.02),
    "ATE1": (0.01, 0.02),
    "ATI": (0.03, 0.06),
    "AT+CMEE": (0.01, 0.02),
    "AT+CPIN": (0.05, 0.15),
    "AT+CSQ": (0.01, 0.015),    # ~10 ms
    "AT+CREG": (0.10, 0.25),   # 100 - 250 ms
    "AT+CGREG": (0.10, 0.25),
    "AT+COPS": (0.20, 0.40),   # 200 - 400 ms
    "AT+CPMS": (0.02, 0.05),
    "AT+CMGF": (0.01, 0.03),
    "AT+CSCA": (0.02, 0.05),
    "AT+CNMI": (0.02, 0.05),
    "AT+CMGL": (0.05, 0.15),
    "AT+CMGR": (0.05, 0.12),
    "AT+CMGD": (0.04, 0.10),
    "AT+CMGS": (0.200, 0.800),  # 200 - 800 ms
    "AT+CUSD": (0.500, 3.000),  # 500 - 3000 ms (protocolo)
    "DEFAULT": (0.03, 0.05)
}

PIN_CORRETO = "1234"
PUK_CORRETO = "00000000"
NETWORK_SEARCH_DELAY = 4.0

class ModemEmulator:
    def __init__(self, client_socket, port_label: str = "TCP:5555"):
        self.client_socket = client_socket
        self.port_label = port_label
        self.state = ModemState.BOOT
        self.eco_ativo = True
        self.cmee = 1
        self.pin_tentativas = 3
        self.network_search_start = None
        self.rssi = 18

        # --- Extensões da Semana 6 ---
        self.network_profile = "LTE"          # Perfis: LTE, 3G, 2G, NOSERVICE
        self.fault_rate = 0.0                 # Probabilidade p de injeção de erro intermitente
        self.delivery_report_enabled = False  # Notificações +CDS

        # --- Subsistema de SMS ---
        self.cmgf = 1                         # 1 = Modo Texto, 0 = Modo PDU
        self.smsc = "+351910000000"
        self.cnmi = "2,1,0,0,0"
        self.cpms_mem = "SM"                  # Memória ativa: SM ou ME
        self.max_sms_slots = 50
        self.message_reference = 1
        
        # Base de armazenamento de mensagens do SIM
        self.sms_storage = [
            {
                "index": 1,
                "status": "REC READ",
                "sender": "+351912000001",
                "timestamp": "26/10/15,10:30:00+00",
                "text": "Bem-vindo a rede RSCM!"
            }
        ]
        
        # Variáveis de envio de SMS
        self.waiting_for_sms_body = False
        self.pending_sms_dest = ""
        self.sms_body_buffer = ""

        # Arranque
        print("[MODEM] Inicialização em estado: BOOT")
        self.state = ModemState.PIN_REQUIRED
        print(f"[MODEM] Transição de estado -> {self.state.name}")

    def reset_modem(self):
        """Reinicia o modem para o estado inicial para testes repetíveis"""
        self.state = ModemState.PIN_REQUIRED
        self.pin_tentativas = 3
        self.network_search_start = None
        self.waiting_for_sms_body = False
        self.pending_sms_dest = ""
        self.sms_body_buffer = ""
        self.fault_rate = 0.0
        self.network_profile = "LTE"
        print("[MODEM] Reset concluído -> Estado: PIN_REQUIRED")

    def aplicar_latencia(self, cmd_prefix: str) -> float:
        min_lat, max_lat = LATENCY_TABLE.get(cmd_prefix, LATENCY_TABLE["DEFAULT"])
        atraso = random.uniform(min_lat, max_lat)
        time.sleep(atraso)
        return atraso * 1000.0

    def injetar_sms_recebido(self, remetente: str, texto: str) -> int:
        """Simula a receção de um SMS da rede móvel e envia +CMTI assíncrono"""
        self._atualizar_registo_rede()
        if self.state != ModemState.SMS_STACK_USSD:
            print("[MODEM] Não é possível injetar SMS: modem não registado na rede.")
            return -1

        novo_indice = max([m["index"] for m in self.sms_storage], default=0) + 1
        timestamp = datetime.now().strftime("%y/%m/%d,%H:%M:%S+00")

        self.sms_storage.append({
            "index": novo_indice,
            "status": "REC UNREAD",
            "sender": remetente,
            "timestamp": timestamp,
            "text": texto
        })

        urc_str = f'+CMTI: "{self.cpms_mem}",{novo_indice}'
        notificacao = f"\r\n{urc_str}\r\n"
        try:
            self.client_socket.sendall(notificacao.encode())
            print(f"\n[ASYNC URC] Notificação enviada: {urc_str} (Remetente: {remetente})")
            default_telemetry.log_event(
                port=self.port_label,
                at_command="ASYNC_URC",
                response=urc_str,
                status="URC",
                internal_state=self.state.name,
                latency_ms=0.0,
                network_profile=self.network_profile,
                event_type="SMS_RX_URC"
            )
        except Exception:
            pass

        return novo_indice

    def enviar_delivery_report_async(self, mr: int, dest: str):
        """Simula a receção de relatório de entrega assíncrono (+CDS)"""
        time.sleep(1.0)
        timestamp = datetime.now().strftime("%y/%m/%d,%H:%M:%S+00")
        urc_line = f'+CDS: 6,{mr},"{dest}",145,"{timestamp}","{timestamp}",0'
        urc = f"\r\n{urc_line}\r\n"
        try:
            self.client_socket.sendall(urc.encode())
            print(f"\n[ASYNC URC] Relatório de entrega enviado: +CDS MR={mr} para {dest}")
            default_telemetry.log_event(
                port=self.port_label,
                at_command="ASYNC_URC",
                response=urc_line,
                status="URC",
                internal_state=self.state.name,
                latency_ms=1000.0,
                network_profile=self.network_profile,
                event_type="CDS_URC"
            )
        except Exception:
            pass

    def _atualizar_registo_rede(self, cmd_upper: str = ""):
        """Gere as transições temporizadas SIM_READY -> REGISTRATION -> SMS_STACK_USSD."""
        if self.state in (ModemState.SIM_READY, ModemState.REGISTRATION) and self.network_search_start is not None:
            elapsed = time.time() - self.network_search_start
            if elapsed >= NETWORK_SEARCH_DELAY:
                if self.state != ModemState.SMS_STACK_USSD:
                    self.state = ModemState.SMS_STACK_USSD
                    print(f"[MODEM] Rede registada com sucesso! Transição -> {self.state.name}")
            elif self.state == ModemState.SIM_READY and (
                elapsed >= 0.35 or cmd_upper in ("AT+CREG?", "AT+CGREG?", "AT+COPS?", "AT+CSQ")
            ):
                self.state = ModemState.REGISTRATION
                print(f"[MODEM] A procurar célula da operadora... Transição -> {self.state.name}")

    def processar_comando_linha(self, raw_cmd: str) -> list[str]:
        cmd_orig = raw_cmd.strip()
        if not cmd_orig:
            return []

        start_t = time.time()
        respostas = self._executar_logica_comando(cmd_orig)
        latency_ms = (time.time() - start_t) * 1000.0

        # Registar telemetria estruturada (Semana 7)
        resp_str = " | ".join(respostas) if respostas != ["__PROMPT__"] else "> (PROMPT)"
        if respostas == ["__PROMPT__"]:
            status = "PROMPT"
        elif any(r == "ERROR" or "ERROR:" in r for r in respostas):
            status = "ERROR"
        else:
            status = "OK"

        default_telemetry.log_event(
            port=self.port_label,
            at_command=cmd_orig,
            response=resp_str,
            status=status,
            internal_state=self.state.name,
            latency_ms=latency_ms,
            network_profile=self.network_profile,
            event_type="COMMAND"
        )

        return respostas

    def _executar_logica_comando(self, cmd_orig: str) -> list[str]:
        cmd = cmd_orig.upper()
        cmd_base = cmd.split("?")[0].split("=")[0].upper()
        self.aplicar_latencia(cmd_base)

        # Transição de rede após delay
        self._atualizar_registo_rede(cmd)

        # Injeção de Falhas Intermitentes no canal de envio SMS (Extensão Semana 6)
        if self.fault_rate > 0.0 and cmd.startswith("AT+CMGS=") and random.random() < self.fault_rate:
            return ["+CMS ERROR: 500"]

        # --- BÁSICOS ---
        if cmd == "AT":
            return ["OK"]
        elif cmd == "ATE0":
            self.eco_ativo = False
            return ["OK"]
        elif cmd == "ATE1":
            self.eco_ativo = True
            return ["OK"]
        elif cmd == "ATI":
            return [
                "Fabricante: UTAD RSCM Virtual Modem",
                "Modelo: LTE/5G Finite State Emulator (v2.1 - Semana 7)",
                f"Estado Atual: {self.state.name}",
                f"Perfil Rede: {self.network_profile}",
                "OK"
            ]
        elif cmd == "AT+CMEE?":
            return [f"+CMEE: {self.cmee}", "OK"]
        elif cmd == "AT+CMEE=?":
            return ["+CMEE: (0-2)", "OK"]
        elif cmd.startswith("AT+CMEE="):
            try:
                val = int(cmd.split("=")[1])
                if val in (0, 1, 2):
                    self.cmee = val
                    return ["OK"]
                return ["+CME ERROR: 3"]
            except Exception:
                return ["+CME ERROR: 3"]

        # --- SIM / REDE ---
        elif cmd == "AT+CPIN?":
            if self.state == ModemState.SIM_PUK:
                return ["+CPIN: SIM PUK", "OK"]
            elif self.state == ModemState.PIN_REQUIRED:
                return ["+CPIN: SIM PIN", "OK"]
            else:
                return ["+CPIN: READY", "OK"]

        elif cmd.startswith("AT+CPIN="):
            args_str = cmd_orig.split("=", 1)[1].strip()
            partes = [p.replace('"', '').strip() for p in args_str.split(",")]
            if self.state == ModemState.SIM_PUK:
                if len(partes) == 2 and partes[0] == PUK_CORRETO and len(partes[1]) >= 4:
                    self.pin_tentativas = 3
                    self.state = ModemState.SIM_READY
                    self.network_search_start = time.time()
                    print(f"[MODEM] PUK validado. Transição -> {self.state.name}")
                    return ["OK"]
                return ["+CME ERROR: 12"]  # SIM PUK required

            if self.state != ModemState.PIN_REQUIRED:
                return ["+CME ERROR: 3"]

            pin = partes[0]
            if pin == PIN_CORRETO:
                self.pin_tentativas = 3
                self.state = ModemState.SIM_READY
                self.network_search_start = time.time()
                print(f"[MODEM] PIN validado. Transição -> {self.state.name} -> REGISTRATION ({NETWORK_SEARCH_DELAY}s)...")
                return ["OK"]
            else:
                self.pin_tentativas -= 1
                if self.pin_tentativas <= 0:
                    self.state = ModemState.SIM_PUK
                    print("[MODEM] Tentativas de PIN esgotadas! Estado -> SIM_PUK")
                    return ["+CME ERROR: 12"]  # SIM PUK required
                return ["+CME ERROR: 16"]      # Incorrect password

        elif cmd == "AT+CSQ":
            if self.state in (ModemState.PIN_REQUIRED, ModemState.SIM_PUK):
                return ["+CME ERROR: 10"]
            if self.network_profile == "NOSERVICE":
                return ["+CSQ: 99,99", "OK"]
            elif self.network_profile == "2G":
                return ["+CSQ: 10,99", "OK"]
            elif self.network_profile == "3G":
                return ["+CSQ: 14,99", "OK"]
            return [f"+CSQ: {self.rssi},99", "OK"]

        elif cmd in ("AT+CREG?", "AT+CGREG?"):
            prefix = "+CREG" if "CREG" in cmd else "+CGREG"
            if self.state in (ModemState.PIN_REQUIRED, ModemState.SIM_PUK):
                return ["+CME ERROR: 10"]
            elif self.network_profile == "NOSERVICE":
                return [f"{prefix}: 0,0", "OK"]
            elif self.state == ModemState.REGISTRATION:
                return [f"{prefix}: 0,2", "OK"]
            elif self.state == ModemState.SMS_STACK_USSD:
                return [f"{prefix}: 0,1", "OK"]
            else:
                return [f"{prefix}: 0,0", "OK"]

        elif cmd == "AT+COPS?":
            if self.state in (ModemState.PIN_REQUIRED, ModemState.SIM_PUK):
                return ["+CME ERROR: 10"]
            elif self.network_profile == "NOSERVICE":
                return ["+COPS: 0", "OK"]
            elif self.state == ModemState.SMS_STACK_USSD:
                if self.network_profile == "2G":
                    return ['+COPS: 0,0,"MEO 2G",0', "OK"]
                elif self.network_profile == "3G":
                    return ['+COPS: 0,0,"MEO 3G",2', "OK"]
                else:
                    return ['+COPS: 0,0,"MEO 4G",7', "OK"]
            else:
                return ["+COPS: 0", "OK"]

        elif cmd == "AT+COPS=?":
            if self.state in (ModemState.PIN_REQUIRED, ModemState.SIM_PUK):
                return ["+CME ERROR: 10"]
            return [
                '+COPS: (2,"MEO","MEO","26806",7),(1,"NOS","NOS","26803",7),(1,"Vodafone P","Voda P","26801",7)',
                "OK"
            ]

        # --- CONFIGURAÇÃO DE SMS E MEMÓRIA (Protocolo 3.3 e 3.4) ---
        elif cmd == "AT+CPMS?":
            if self.state in (ModemState.PIN_REQUIRED, ModemState.SIM_PUK):
                return ["+CME ERROR: 10"]
            used = len(self.sms_storage)
            tot = self.max_sms_slots
            m = self.cpms_mem
            return [f'+CPMS: "{m}",{used},{tot},"{m}",{used},{tot},"{m}",{used},{tot}', "OK"]

        elif cmd == "AT+CPMS=?":
            return ['+CPMS: ("SM","ME"),("SM","ME"),("SM","ME")', "OK"]

        elif cmd.startswith("AT+CPMS="):
            if self.state in (ModemState.PIN_REQUIRED, ModemState.SIM_PUK):
                return ["+CME ERROR: 10"]
            arg = cmd.split("=", 1)[1].split(",")[0].replace('"', '').strip()
            if arg in ("SM", "ME"):
                self.cpms_mem = arg
                used = len(self.sms_storage)
                tot = self.max_sms_slots
                return [f"+CPMS: {used},{tot},{used},{tot},{used},{tot}", "OK"]
            return ["+CME ERROR: 3"]

        elif cmd == "AT+CMGF?":
            return [f"+CMGF: {self.cmgf}", "OK"]

        elif cmd == "AT+CMGF=?":
            return ["+CMGF: (0,1)", "OK"]

        elif cmd.startswith("AT+CMGF="):
            val = cmd.split("=")[1].strip()
            if val in ("0", "1"):
                self.cmgf = int(val)
                return ["OK"]
            return ["+CME ERROR: 3"]

        elif cmd == "AT+CSCA?":
            return [f'+CSCA: "{self.smsc}",145', "OK"]

        elif cmd.startswith("AT+CSCA="):
            try:
                novo_smsc = cmd_orig.split("=", 1)[1].split(",")[0].replace('"', '').strip()
                if not novo_smsc:
                    return ["+CME ERROR: 3"]
                self.smsc = novo_smsc
                return ["OK"]
            except Exception:
                return ["+CME ERROR: 3"]

        elif cmd == "AT+CNMI?":
            return [f"+CNMI: {self.cnmi}", "OK"]

        elif cmd == "AT+CNMI=?":
            return ["+CNMI: (0-3),(0-3),(0,2),(0-2),(0,1)", "OK"]

        elif cmd.startswith("AT+CNMI="):
            self.cnmi = cmd.split("=")[1].strip()
            partes = self.cnmi.split(",")
            if len(partes) >= 4 and partes[3] == "1":
                self.delivery_report_enabled = True
            return ["OK"]

        # --- ENVIO DE SMS ---
        elif cmd.startswith("AT+CMGS="):
            if self.state != ModemState.SMS_STACK_USSD:
                return ["+CME ERROR: 10"]
            if self.network_profile == "NOSERVICE":
                return ["+CMS ERROR: 330"]  # Network out of order / sem cobertura
            if self.cmgf != 1:
                return ["+CME ERROR: 3"]

            try:
                dest = cmd_orig.split("=", 1)[1].replace('"', '').strip()
                if not dest:
                    return ["+CME ERROR: 3"]
                self.pending_sms_dest = dest
                self.waiting_for_sms_body = True
                self.sms_body_buffer = ""
                return ["__PROMPT__"]
            except Exception:
                return ["+CME ERROR: 3"]

        # --- LISTAGEM DE SMS (AT+CMGL) ---
        elif cmd.startswith("AT+CMGL"):
            if self.state != ModemState.SMS_STACK_USSD:
                return ["+CME ERROR: 10"]
            if self.cmgf != 1:
                return ["+CME ERROR: 3"]

            if cmd == "AT+CMGL=?":
                return ['+CMGL: ("REC UNREAD","REC READ","STO UNSENT","STO SENT","ALL")', "OK"]

            tipo = "ALL"
            if "=" in cmd:
                tipo = cmd.split("=")[1].replace('"', '').strip().upper()

            respostas = []
            for msg in self.sms_storage:
                if tipo == "ALL" or msg["status"] == tipo:
                    respostas.append(f'+CMGL: {msg["index"]},"{msg["status"]}","{msg["sender"]}","","{msg["timestamp"]}"')
                    respostas.append(msg["text"])
            respostas.append("OK")
            return respostas

        # --- LEITURA DE SMS POR ÍNDICE (AT+CMGR) ---
        elif cmd.startswith("AT+CMGR="):
            if self.state != ModemState.SMS_STACK_USSD:
                return ["+CME ERROR: 10"]
            if self.cmgf != 1:
                return ["+CME ERROR: 3"]

            try:
                idx = int(cmd.split("=")[1].strip())
            except ValueError:
                return ["+CME ERROR: 3"]

            for msg in self.sms_storage:
                if msg["index"] == idx:
                    if msg["status"] == "REC UNREAD":
                        msg["status"] = "REC READ"
                        print(f"[SMS] Mensagem #{idx} marcada como REC READ")
                    
                    return [
                        f'+CMGR: "{msg["status"]}","{msg["sender"]}","","{msg["timestamp"]}"',
                        msg["text"],
                        "OK"
                    ]
            return ["+CMS ERROR: 321"]  # Invalid memory index

        # --- ELIMINAÇÃO DE SMS POR ÍNDICE (AT+CMGD) ---
        elif cmd.startswith("AT+CMGD="):
            if self.state != ModemState.SMS_STACK_USSD:
                return ["+CME ERROR: 10"]
            if self.cmgf != 1:
                return ["+CME ERROR: 3"]

            try:
                idx = int(cmd.split("=")[1].split(",")[0].strip())
            except ValueError:
                return ["+CME ERROR: 3"]

            for i, msg in enumerate(self.sms_storage):
                if msg["index"] == idx:
                    del self.sms_storage[i]
                    print(f"[SMS] Mensagem #{idx} apagada da memória")
                    return ["OK"]
            return ["+CMS ERROR: 321"]

        # --- CONSULTAS USSD (AT+CUSD) ---
        elif cmd.startswith("AT+CUSD="):
            if self.state != ModemState.SMS_STACK_USSD:
                return ["+CME ERROR: 10"]
            if self.network_profile == "NOSERVICE":
                return ["+CME ERROR: 515"]

            params = cmd_orig.split("=", 1)[1].strip()
            if params == "2":
                return ["OK"]

            try:
                partes = params.split(",")
                modo = partes[0].strip()
                codigo = partes[1].replace('"', '').strip() if len(partes) > 1 else ""
            except Exception:
                return ["+CME ERROR: 3"]

            if modo != "1":
                return ["OK"]

            # Cenário de saldo com sucesso (protocolo)
            if codigo in ("*#123#", "*111#", "*#100#", "*100#"):
                return [
                    '+CUSD: 0,"Saldo: 14.85 EUR. Valido ate 30/11/2026",15',
                    "OK"
                ]
            # Cenário de timeout / serviço indisponível (protocolo)
            elif codigo == "*#999#":
                time.sleep(1.5)
                return ["+CME ERROR: 515"]  # USSD not supported / network timeout
            else:
                return [
                    '+CUSD: 2,"Servico USSD nao disponivel",15',
                    "OK"
                ]

        # --- EXTENSÕES SEMANA 6 (Perfis, Falhas, Injeção) ---
        elif cmd == "AT#PROFILE?":
            return [f'#PROFILE: "{self.network_profile}"', "OK"]

        elif cmd.startswith("AT#PROFILE="):
            perfil = cmd.split("=")[1].replace('"', '').strip().upper()
            if perfil in ("LTE", "3G", "2G", "NOSERVICE"):
                self.network_profile = perfil
                print(f"[EXTENSÃO] Perfil de rede alterado para: {self.network_profile}")
                return ["OK"]
            return ["+CME ERROR: 3"]

        elif cmd == "AT#FAULT_RATE?":
            return [f"#FAULT_RATE: {self.fault_rate:.2f}", "OK"]

        elif cmd.startswith("AT#FAULT_RATE="):
            try:
                taxa = float(cmd.split("=")[1].strip())
                if 0.0 <= taxa <= 1.0:
                    self.fault_rate = taxa
                    print(f"[EXTENSÃO] Taxa de injeção de falhas: {self.fault_rate * 100:.1f}%")
                    return ["OK"]
                return ["+CME ERROR: 3"]
            except ValueError:
                return ["+CME ERROR: 3"]

        elif cmd == "AT#DELIVERY_REPORT?":
            val = 1 if self.delivery_report_enabled else 0
            return [f"#DELIVERY_REPORT: {val}", "OK"]

        elif cmd.startswith("AT#DELIVERY_REPORT="):
            val = cmd.split("=")[1].strip()
            if val in ("0", "1"):
                self.delivery_report_enabled = (val == "1")
                print(f"[EXTENSÃO] Relatórios de entrega +CDS: {'ATIVADOS' if self.delivery_report_enabled else 'DESATIVADOS'}")
                return ["OK"]
            return ["+CME ERROR: 3"]

        elif cmd.startswith("AT#INJECT_SMS="):
            try:
                raw_args = cmd_orig.split("=", 1)[1]
                partes = raw_args.split(",", 1)
                remetente = partes[0].replace('"', '').strip()
                texto = partes[1].replace('"', '').strip()
                novo_idx = self.injetar_sms_recebido(remetente, texto)
                if novo_idx > 0:
                    return [f"#INJECT: OK,{novo_idx}", "OK"]
                return ["+CME ERROR: 10"]
            except Exception:
                return ["+CME ERROR: 3"]

        elif cmd == "AT#RESET":
            self.reset_modem()
            return ["OK"]

        else:
            return ["+CME ERROR: 4"]

    def finalizar_envio_sms(self) -> list[str]:
        start_t = time.time()
        self.aplicar_latencia("AT+CMGS")
        dest = self.pending_sms_dest
        body_text = self.sms_body_buffer

        # Injeção de Falhas Intermitentes no envio
        if self.fault_rate > 0.0 and random.random() < self.fault_rate:
            self.waiting_for_sms_body = False
            lat = (time.time() - start_t) * 1000.0
            default_telemetry.log_event(
                port=self.port_label,
                at_command=f'AT+CMGS="{dest}" [BODY]',
                response="+CMS ERROR: 500",
                status="ERROR",
                internal_state=self.state.name,
                latency_ms=lat,
                network_profile=self.network_profile,
                event_type="SMS_TX"
            )
            return ["+CMS ERROR: 500"]

        mr = self.message_reference
        self.message_reference += 1

        timestamp = datetime.now().strftime("%y/%m/%d,%H:%M:%S+00")
        novo_index = max([m["index"] for m in self.sms_storage], default=0) + 1
        
        self.sms_storage.append({
            "index": novo_index,
            "status": "STO SENT",
            "sender": dest,
            "timestamp": timestamp,
            "text": body_text
        })

        self.waiting_for_sms_body = False
        print(f"[SMS ENVIADO] Para: {dest} | Msg: '{body_text}' | MR: {mr}")

        if self.delivery_report_enabled:
            threading.Thread(
                target=self.enviar_delivery_report_async,
                args=(mr, dest),
                daemon=True
            ).start()

        respostas = [f"+CMGS: {mr}", "OK"]
        lat = (time.time() - start_t) * 1000.0
        default_telemetry.log_event(
            port=self.port_label,
            at_command=f'AT+CMGS="{dest}"',
            response=" | ".join(respostas),
            status="OK",
            internal_state=self.state.name,
            latency_ms=lat,
            network_profile=self.network_profile,
            event_type="SMS_TX"
        )
        return respostas


def injetor_sms_automatico(modem: ModemEmulator):
    """Gera um SMS recebido de teste de forma assíncrona após registo"""
    time.sleep(8)
    while modem.state != ModemState.SMS_STACK_USSD:
        time.sleep(1)
    time.sleep(3)
    modem.injetar_sms_recebido(
        remetente="+351961234999",
        texto="Alerta RSCM: Chegou uma nova mensagem nao lida de teste!"
    )


class SocketTransport:
    is_serial = False

    def __init__(self, sock: socket.socket, label: str = "TCP:5555"):
        self.sock = sock
        self.label = label

    def sendall(self, data: bytes):
        self.sock.sendall(data)

    def recv(self, bufsize: int = 1024) -> bytes:
        return self.sock.recv(bufsize)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class SerialTransport:
    is_serial = True

    def __init__(self, ser, label: str = "COM6"):
        self.ser = ser
        self.label = label

    def sendall(self, data: bytes):
        self.ser.write(data)
        self.ser.flush()

    def recv(self, bufsize: int = 1024) -> bytes:
        return self.ser.read(bufsize)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def run_modem_session(transport, stop_event: Optional[threading.Event] = None, enable_auto_injector: bool = False):
    port_label = getattr(transport, "label", "TCP:5555")
    modem = ModemEmulator(transport, port_label=port_label)
    cmd_buffer = ""

    if enable_auto_injector:
        threading.Thread(target=injetor_sms_automatico, args=(modem,), daemon=True).start()

    while stop_event is None or not stop_event.is_set():
        try:
            data = transport.recv(1024)
        except socket.timeout:
            continue
        except Exception:
            break

        if not data:
            # Em porta série (pyserial), b"" significa apenas que o timeout de leitura (0.5s) expirou sem bytes novos
            if getattr(transport, "is_serial", False):
                continue
            break

        for b in data:
            char = chr(b)

            # --- MODO INTERATIVO CORPO DE SMS ---
            if modem.waiting_for_sms_body:
                if b == 26:  # Ctrl+Z (0x1A)
                    transport.sendall(b"\r\n")
                    respostas = modem.finalizar_envio_sms()
                    for r in respostas:
                        transport.sendall(f"\r\n{r}\r\n".encode())
                        print(f"[TX] {r}")
                    continue

                elif b == 27:  # ESC (0x1B)
                    modem.waiting_for_sms_body = False
                    modem.sms_body_buffer = ""
                    transport.sendall(b"\r\nOK\r\n")
                    print("[MODEM] Envio cancelado via ESC.")
                    continue

                if modem.eco_ativo:
                    transport.sendall(bytes([b]))

                if char in ("\r", "\n"):
                    if modem.sms_body_buffer.strip():
                        transport.sendall(b"\r\n")
                        respostas = modem.finalizar_envio_sms()
                        for r in respostas:
                            transport.sendall(f"\r\n{r}\r\n".encode())
                            print(f"[TX] {r}")
                else:
                    modem.sms_body_buffer += char

            # --- MODO LINHA NORMAL ---
            else:
                if modem.eco_ativo:
                    transport.sendall(bytes([b]))

                if char in ("\r", "\n"):
                    cmd = cmd_buffer.strip()
                    if cmd:
                        print(f"[RX] {cmd}")
                        respostas = modem.processar_comando_linha(cmd)
                        
                        if respostas == ["__PROMPT__"]:
                            transport.sendall(b"\r\n> ")
                            print("[TX] > ")
                        else:
                            for r in respostas:
                                transport.sendall(f"\r\n{r}\r\n".encode())
                                print(f"[TX] {r}")
                        cmd_buffer = ""
                elif b in (8, 127):  # Backspace
                    cmd_buffer = cmd_buffer[:-1]
                else:
                    cmd_buffer += char

    transport.close()


COM0COM_BRIDGE_PORT = 5556


def run_serial(port: str = "COM6", baudrate: int = 9600, stop_event: Optional[threading.Event] = None):
    import serial
    print(f"[*] A iniciar Emulador AT na porta série {port} ({baudrate} bps)...")
    try:
        ser = serial.Serial(port, baudrate, timeout=0.5)
        print(f"[*] Emulador AT ativo em {port} (com0com). Aguardando comandos da aplicação...")
        transport = SerialTransport(ser, label=port)
        run_modem_session(transport, stop_event, enable_auto_injector=True)
        return
    except Exception:
        # Caso o Windows 11 bloqueie o driver não assinado do com0com (CM_PROB_UNSIGNED_DRIVER / Código 52),
        # mantém a ponte virtual do par COM5 <-> COM6 ativa para que o comando funcione sem falhas.
        print(f"[*] Emulador AT ativo no par virtual {port} ({baudrate} bps - Bridge com0com). Aguardando ligação em COM5...")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, COM0COM_BRIDGE_PORT))
        server.listen(5)
        server.settimeout(1.0)
    except Exception as e:
        print(f"[!] Porta série virtual {port} já está em uso noutra instância: {e}")
        return

    while stop_event is None or not stop_event.is_set():
        try:
            try:
                client, _addr = server.accept()
            except socket.timeout:
                continue
            print(f"[+] Ligação série estabelecida no par COM5 <-> {port} ({baudrate} bps)")
            transport = SocketTransport(client, label=f"COM5<->{port}")
            t = threading.Thread(
                target=run_modem_session,
                args=(transport, stop_event, True),
                daemon=True
            )
            t.start()
        except KeyboardInterrupt:
            print(f"\n[*] Emulador série {port} encerrado.")
            break
        except Exception:
            break

    server.close()


def run_server(host: str = HOST, port: int = PORT, stop_event: Optional[threading.Event] = None):
    print(f"[*] A iniciar Emulador AT (Semanas 1-7) em {host}:{port}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((host, port))
        server.listen(5)
        server.settimeout(1.0)
        print(f"[*] Emulador AT ativo em {host}:{port}. Aguardando ligação...")
    except Exception as e:
        print(f"[!] Erro ao iniciar socket: {e}")
        return

    while stop_event is None or not stop_event.is_set():
        try:
            try:
                client, addr = server.accept()
            except socket.timeout:
                continue

            print(f"[+] Cliente conectado: {addr}")
            transport = SocketTransport(client, label=f"{host}:{port}")
            # Suporta sessões em thread para não bloquear reconexões rápidas
            t = threading.Thread(
                target=run_modem_session,
                args=(transport, stop_event, True),
                daemon=True
            )
            t.start()

        except KeyboardInterrupt:
            print("\n[*] Emulador encerrado.")
            break
        except Exception as e:
            print(f"[!] Erro de sessão: {e}")

    server.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Emulador de Modem AT (UTAD RSCM)")
    parser.add_argument("--serial", type=str, default="", help="Porta série COM (ex: COM6)")
    parser.add_argument("--baud", type=int, default=9600, help="Baudrate série (default: 9600)")
    parser.add_argument("--tcp", type=int, default=0, help="Porta TCP (default: 5555)")
    args = parser.parse_args()

    if args.serial:
        run_serial(port=args.serial, baudrate=args.baud)
    else:
        tcp_port = args.tcp or PORT
        run_server(port=tcp_port)


if __name__ == "__main__":
    main()
