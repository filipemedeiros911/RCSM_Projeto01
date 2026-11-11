"""
Gateway Bidirecional Email <-> SMS (Semana 6 - Aplicação de Alto Nível 2)
Disciplina: Redes Sem Fios e Comunicações Móveis (RSCM)
Universidade de Trás-os-Montes e Alto Douro (UTAD)

Funcionalidades:
- Conversão Bidirecional:
  1. SMS -> Email:
     Recebe SMS no formato 'EMAIL:destinatario@dominio.com | Assunto | Mensagem',
     valida o endereço, converte em email eletrónico (simulado/outbox), e responde
     ao telemóvel com recibo de sucesso ou diagnóstico de erro sintático.
  2. Email -> SMS:
     Recebe mensagens de email eletrónico e envia para o telemóvel de destino via SMS
     utilizando a política de retry automática do ModemClient.
- Limpeza automática de mensagens da memória do SIM após encaminhamento (AT+CMGD).
- Registo de tráfego, contadores de mensagens e estatísticas de fiabilidade.
"""

import re
import time
import threading
from typing import Dict, Any, List, Optional
from modem_client import ModemClient

class EmailSMSGateway:
    def __init__(self, client: ModemClient, gateway_email: str = "gateway@rscm.utad.pt"):
        """
        Inicializa o Gateway Email <-> SMS.
        :param client: Instância de ModemClient ligada ao emulador.
        :param gateway_email: Endereço do gateway para identificação de tráfego.
        """
        self.client = client
        self.gateway_email = gateway_email
        self.is_active = False

        # Filas de mensagens simuladas
        self.email_outbox: List[Dict[str, Any]] = []
        self.sms_outbox: List[Dict[str, Any]] = []

        # Métricas de tráfego
        self.stats = {
            "sms_received": 0,
            "sms_to_email_success": 0,
            "sms_to_email_errors": 0,
            "email_to_sms_sent": 0,
            "email_to_sms_failed": 0
        }

        self._listener_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """Inicia o gateway e regista os listeners para eventos URC"""
        self.is_active = True
        self.client.register_urc_callback(self._on_urc_event)
        
        # Processar mensagens acumuladas
        self.scan_and_process_pending()

        # Thread de varrimento de salvaguarda
        self._listener_thread = threading.Thread(target=self._periodic_worker, daemon=True)
        self._listener_thread.start()
        print(f"[GATEWAY] Gateway Email <-> SMS ativo ({self.gateway_email})")
        self.print_stats()

    def stop(self):
        """Termina o gateway"""
        self.is_active = False
        print("[GATEWAY] Gateway Email <-> SMS terminado.")

    def _on_urc_event(self, urc_type: str, data: Dict[str, Any]):
        """Recebe notificações +CMTI assíncronas do modem"""
        if not self.is_active:
            return
        if urc_type == "CMTI":
            index = data.get("index")
            if index is not None:
                self._process_message_index(index)

    def _periodic_worker(self):
        """Varrimento periódico de segurança"""
        while self.is_active:
            time.sleep(3.0)
            if self.is_active:
                self.scan_and_process_pending()

    def scan_and_process_pending(self):
        """Verifica a caixa de entrada para mensagens com status REC UNREAD"""
        with self._lock:
            messages = self.client.list_sms(tag="REC UNREAD")
            for msg in messages:
                self._process_incoming_sms(msg["index"], msg["sender"], msg["text"])

    def _process_message_index(self, index: int):
        with self._lock:
            msg = self.client.read_sms(index)
            if msg:
                self._process_incoming_sms(index, msg["sender"], msg["text"])

    def _process_incoming_sms(self, index: int, sender: str, text: str):
        """
        Processa um SMS recebido para determinar se é um comando de encaminhamento para email.
        Formato suportado:
          EMAIL:dest@dominio.com | Assunto | Corpo da mensagem
          ou
          EMAIL:dest@dominio.com Corpo da mensagem
        """
        self.stats["sms_received"] += 1
        t_clean = text.strip()

        # Ignorar mensagens de sistema emitidas pelo próprio gateway
        if t_clean.startswith("[GATEWAY]"):
            self.client.delete_sms(index)
            return

        if not t_clean.upper().startswith("EMAIL:"):
            print(f"[GATEWAY] SMS ignorado (nao e comando de email): '{t_clean}'")
            self.client.delete_sms(index)
            return

        # Remover o prefixo "EMAIL:"
        payload = t_clean[6:].strip()
        dest_email = ""
        subject = "Mensagem SMS"
        body = ""

        # Formato 1: Delimitado por '|' (EMAIL:dest@dom.pt | Assunto | Texto)
        if "|" in payload:
            parts = [p.strip() for p in payload.split("|", 2)]
            dest_email = parts[0]
            if len(parts) >= 2:
                subject = parts[1] or "Mensagem SMS"
            if len(parts) >= 3:
                body = parts[2]
        else:
            # Formato 2: Delimitado por espaço (EMAIL:dest@dom.pt Texto)
            space_split = payload.split(" ", 1)
            dest_email = space_split[0].strip()
            body = space_split[1].strip() if len(space_split) > 1 else "(sem conteudo)"

        # Validar endereço de email através de regex
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, dest_email):
            print(f"[GATEWAY] Endereco de email invalido: '{dest_email}' de {sender}")
            self.stats["sms_to_email_errors"] += 1
            
            # Notificar o utilizador do erro
            msg_erro = f"[GATEWAY] Erro: Endereco '{dest_email}' invalido. Formato: EMAIL:destino@dominio.pt | Assunto | Texto"
            self.client.send_sms(sender, msg_erro)
            self.client.delete_sms(index)
            return

        # Converter e despachar para a fila de saída de email
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        email_record = {
            "timestamp": timestamp,
            "from_sms": sender,
            "to_email": dest_email,
            "subject": subject,
            "body": body,
            "status": "DISPATCHED"
        }
        self.email_outbox.append(email_record)
        self.stats["sms_to_email_success"] += 1

        print(f"\n[GATEWAY: SMS -> EMAIL] Sucesso!")
        print(f" De Telemovel : {sender}")
        print(f" Para Email    : {dest_email}")
        print(f" Assunto       : {subject}")
        print(f" Conteudo      : {body}\n")

        # Enviar SMS de recibo de entrega ao telemóvel remetente
        recibo = f"[GATEWAY] O seu email para {dest_email} foi reencaminhado com sucesso! Assunto: {subject}"
        self.client.send_sms(sender, recibo)

        # Apagar SMS processado da memória
        self.client.delete_sms(index)

    def relay_email_to_sms(self, from_email: str, to_phone: str, subject: str, body: str) -> bool:
        """
        Encaminha um email eletrónico para a rede móvel como SMS (Email -> SMS).
        Utiliza o cliente com Retry Policy automático.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        # Formatar corpo para cumprir formato SMS
        header = f"[EMAIL de {from_email}] {subject}: "
        corpo_restante = 160 - len(header)
        texto_final = header + (body[:corpo_restante] if corpo_restante > 0 else "")

        print(f"[GATEWAY: EMAIL -> SMS] A enviar para {to_phone}: '{texto_final}'")
        res = self.client.send_sms(to_phone, texto_final)

        if res["success"]:
            self.stats["email_to_sms_sent"] += 1
            self.sms_outbox.append({
                "timestamp": timestamp,
                "from_email": from_email,
                "to_phone": to_phone,
                "text": texto_final,
                "mr": res.get("mr", -1),
                "attempts": res.get("attempts", 1),
                "status": "DELIVERED"
            })
            print(f"[GATEWAY] SMS entregue com sucesso a {to_phone} (MR: {res.get('mr')}, Tentativas: {res.get('attempts')})")
            return True
        else:
            self.stats["email_to_sms_failed"] += 1
            print(f"[GATEWAY] Falha ao enviar SMS para {to_phone}: {res.get('error')}")
            return False

    def print_stats(self):
        """Apresenta as estatísticas de tráfego do gateway"""
        print("\n" + "=" * 55)
        print(f" ESTATISTICAS DO GATEWAY EMAIL <-> SMS ({self.gateway_email})")
        print("-" * 55)
        print(f" SMS Recebidos Totais         : {self.stats['sms_received']}")
        print(f" SMS -> Email Reencaminhados  : {self.stats['sms_to_email_success']}")
        print(f" SMS -> Email Erros Sintaxe   : {self.stats['sms_to_email_errors']}")
        print(f" Email -> SMS Enviados        : {self.stats['email_to_sms_sent']}")
        print(f" Email -> SMS Falhados        : {self.stats['email_to_sms_failed']}")
        print(f" Total Emails em Outbox       : {len(self.email_outbox)}")
        print("=" * 55 + "\n")


# Modo de execução autónomo
if __name__ == "__main__":
    import sys
    print("=" * 60)
    print(" RSCM 2026/2027 - Gateway Email <-> SMS (Semana 6)")
    print("=" * 60)

    port = "COM5" if len(sys.argv) > 1 and sys.argv[1].upper().startswith("COM") else "127.0.0.1"
    baud_or_tcp = 9600 if port.startswith("COM") else (int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5555)

    print(f"A ligar ao modem em {port}:{baud_or_tcp}...")
    client = ModemClient(port, baud_or_tcp)
    if not client.connect():
        print(f"ERRO: Nao foi possivel ligar ao modem em {port}:{baud_or_tcp}.")
        print("Certifique-se de que o at_emulator.py esta em execucao.")
        sys.exit(1)

    print("A inicializar modem (PIN 1234)...")
    client.initialize("1234", wait_network_s=5.0)

    gateway = EmailSMSGateway(client)
    gateway.start()

    print("\nO Gateway esta ativo!")
    print("Exemplos de utilizacao:")
    print(" 1. SMS -> Email: Envie um SMS com o formato:")
    print("    EMAIL:aluno@utad.pt | Projeto RSCM | O trabalho da semana 6 esta pronto.")
    print(" 2. Injetar SMS de teste no emulador:")
    print("    AT#INJECT_SMS=\"+351912345678\",\"EMAIL:teste@utad.pt | Ola | Teste gateway\"")
    print("\nPressione Ctrl+C para terminar.\n")

    try:
        while True:
            time.sleep(10)
            gateway.print_stats()
    except KeyboardInterrupt:
        print("\nA encerrar Gateway...")
        gateway.stop()
        client.disconnect()
        print("Concluido.")
