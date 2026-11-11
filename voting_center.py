"""
Centro de Votação por SMS (Semana 6 - Aplicação de Alto Nível 1)
Disciplina: Redes Sem Fios e Comunicações Móveis (RSCM)
Universidade de Trás-os-Montes e Alto Douro (UTAD)

Funcionalidades:
- Gestão de sondagens/votações com opções parametrizáveis.
- Processamento de votos recebidos via SMS (através de URC +CMTI ou varrimento periódico).
- Validação de regras de negócio: 1 voto por número de telemóvel (rejeição de duplicados).
- Envio de SMS de confirmação (recibo) ao votante com a opção escolhida.
- Limpeza automática de mensagens processadas da memória do SIM (AT+CMGD).
- Apuramento em tempo real dos resultados com percentagens e vencedor.
"""

import time
import threading
from typing import Dict, Any, Optional
from modem_client import ModemClient

class VotingCenter:
    def __init__(self, client: ModemClient, question: str, options: Dict[str, str]):
        """
        Inicializa o Centro de Votação.
        :param client: Instância configurada de ModemClient.
        :param question: Pergunta da votação (ex: 'Qual a sua linguagem favorita?').
        :param options: Dicionário de opções válidas (ex: {'1': 'Python', '2': 'C++', '3': 'Rust'}).
        """
        self.client = client
        self.question = question
        self.options = options  # ex: {"1": "Opção A", "2": "Opção B"}
        
        # Estruturas de dados para controlo da votação
        # voters: número de telefone -> opção escolhida
        self.voters: Dict[str, str] = {}
        # tally: opção -> contagem de votos
        self.tally: Dict[str, int] = {k: 0 for k in options.keys()}
        
        self.is_active = False
        self._listener_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Histórico de transações para auditoria
        self.audit_log = []

    def start(self):
        """Inicia o centro de votação e o registo de listeners para mensagens SMS"""
        self.is_active = True
        self.client.register_urc_callback(self._on_urc_event)
        
        # Processar mensagens não lidas que já possam existir na memória do SIM
        self.scan_and_process_pending()
        
        # Thread de verificação periódica de segurança
        self._listener_thread = threading.Thread(target=self._periodic_worker, daemon=True)
        self._listener_thread.start()
        print(f"[VOTACAO] Centro de Votacao iniciado: '{self.question}'")
        self.print_status()

    def stop(self):
        """Termina o centro de votação"""
        self.is_active = False
        print("[VOTACAO] Centro de Votacao terminado.")

    def _on_urc_event(self, urc_type: str, data: Dict[str, Any]):
        """Callback acionado automaticamente quando o modem emite um URC (+CMTI)"""
        if not self.is_active:
            return
        if urc_type == "CMTI":
            index = data.get("index")
            if index is not None:
                self._process_message_index(index)

    def _periodic_worker(self):
        """Thread periódica que garante a leitura de mensagens mesmo se o URC for perdido"""
        while self.is_active:
            time.sleep(3.0)
            if self.is_active:
                self.scan_and_process_pending()

    def scan_and_process_pending(self):
        """Lê todas as mensagens não lidas (REC UNREAD) da memória e processa os votos"""
        with self._lock:
            messages = self.client.list_sms(tag="REC UNREAD")
            for msg in messages:
                self._process_sms_data(msg["index"], msg["sender"], msg["text"])

    def _process_message_index(self, index: int):
        """Lê uma mensagem específica por índice e processa o seu conteúdo"""
        with self._lock:
            msg = self.client.read_sms(index)
            if msg:
                self._process_sms_data(index, msg["sender"], msg["text"])

    def _process_sms_data(self, index: int, sender: str, raw_text: str):
        """Aplica as regras de negócio de voto, responde ao remetente e apaga o SMS"""
        text_clean = raw_text.strip().upper()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Verificar se o número já votou
        if sender in self.voters:
            motivo = f"Voto rejeitado: {sender} ja tinha votado na opcao {self.voters[sender]}."
            print(f"[VOTACAO] {motivo}")
            self.audit_log.append({"timestamp": timestamp, "sender": sender, "action": "REJECT_DUPLICATE", "text": raw_text})
            
            # Enviar SMS a informar da rejeição por voto duplicado
            msg_resposta = f"[SISTEMA DE VOTACAO] O seu voto ja se encontra registado ({self.voters[sender]}). Apenas 1 voto por numero e permitido."
            self.client.send_sms(sender, msg_resposta)
            
            # Limpar SMS processado da memória do SIM
            self.client.delete_sms(index)
            return

        # 2. Identificar se o texto corresponde a uma opção válida
        voto_opcao = None
        # Correspondência direta pela chave (ex: "1", "2")
        if text_clean in self.options:
            voto_opcao = text_clean
        else:
            # Correspondência pelo nome da opção (ex: "PYTHON")
            for opt_key, opt_name in self.options.items():
                if text_clean == opt_name.strip().upper():
                    voto_opcao = opt_key
                    break

        if voto_opcao:
            # Registar o voto com sucesso
            self.voters[sender] = voto_opcao
            self.tally[voto_opcao] += 1
            nome_opcao = self.options[voto_opcao]
            
            print(f"[VOTACAO] [VOTO VALIDO] Remetente {sender} votou em [{voto_opcao}] {nome_opcao}")
            self.audit_log.append({"timestamp": timestamp, "sender": sender, "action": "ACCEPT_VOTE", "option": voto_opcao})

            # Enviar SMS de recibo / confirmação
            msg_recibo = f"[SISTEMA DE VOTACAO] Voto confirmado com sucesso na opcao '{nome_opcao}'. Obrigado pela participacao!"
            self.client.send_sms(sender, msg_recibo)
        else:
            # Opção inválida
            opcoes_validas = ", ".join([f"{k}={v}" for k, v in self.options.items()])
            print(f"[VOTACAO] [VOTO INVALIDO] Remetente {sender} enviou opcao desconhecida: '{raw_text}'")
            self.audit_log.append({"timestamp": timestamp, "sender": sender, "action": "REJECT_INVALID", "text": raw_text})
            
            msg_invalido = f"[SISTEMA DE VOTACAO] Opcao '{raw_text}' invalida. Escolha uma das seguintes opcoes: {opcoes_validas}"
            self.client.send_sms(sender, msg_invalido)

        # 3. Limpar SMS processado da memória do SIM para não esgotar capacidade
        self.client.delete_sms(index)

    def get_results(self) -> Dict[str, Any]:
        """Calcula o sumário dos resultados e percentagens"""
        total_votos = sum(self.tally.values())
        resultados = {}
        vencedor = None
        max_votos = -1

        for opt_key, nome in self.options.items():
            qtd = self.tally[opt_key]
            pct = (qtd / total_votos * 100.0) if total_votos > 0 else 0.0
            resultados[opt_key] = {
                "name": nome,
                "votes": qtd,
                "percentage": round(pct, 2)
            }
            if qtd > max_votos and total_votos > 0:
                max_votos = qtd
                vencedor = nome

        return {
            "question": self.question,
            "total_votes": total_votos,
            "results": resultados,
            "winner": vencedor if total_votos > 0 else "Sem votos"
        }

    def print_status(self):
        """Exibe o placar de votação no terminal"""
        res = self.get_results()
        print("\n" + "=" * 55)
        print(f" PERGUNTA: {res['question']}")
        print(f" TOTAL DE VOTOS: {res['total_votes']}")
        print("-" * 55)
        for opt_key, data in res["results"].items():
            barra = "#" * int(data["percentage"] / 5)
            print(f" [{opt_key}] {data['name']:<18} : {data['votes']:>3} votos ({data['percentage']:>5.1f}%) | {barra}")
        print("-" * 55)
        print(f" LIDER / VENCEDOR: {res['winner']}")
        print("=" * 55 + "\n")


# Modo autónomo para testes ou execução em linha de comando
if __name__ == "__main__":
    import sys
    print("=" * 60)
    print(" RSCM 2026/2027 - Centro de Votacao SMS (Semana 6)")
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
    if not client.initialize("1234", wait_network_s=5.0):
        print("Aviso: Inicializacao de rede com avisos, a prosseguir...")

    # Configuração de uma votação de exemplo
    pergunta = "Qual e o melhor protocolo para IoT?"
    opcoes = {
        "1": "MQTT",
        "2": "CoAP",
        "3": "LoRaWAN",
        "4": "NB-IoT"
    }

    center = VotingCenter(client, pergunta, opcoes)
    center.start()

    print("\nO Centro de Votacao esta ativo e a aguardar votos por SMS.")
    print("Pode injetar votos no emulador via AT#INJECT_SMS=\"+351910000001\",\"1\"")
    print("Pressione Ctrl+C para sair e ver os resultados finais.\n")

    try:
        while True:
            time.sleep(5)
            center.print_status()
    except KeyboardInterrupt:
        print("\nA encerrar Centro de Votacao...")
        center.stop()
        client.disconnect()
        print("Concluido.")
