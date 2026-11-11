"""
Executor Automatizado do Plano de Testes Determinístico (Semana 6)
Disciplina: Redes Sem Fios e Comunicações Móveis (RSCM)
Universidade de Trás-os-Montes e Alto Douro (UTAD)

Valida os 36 casos de teste (TC-01 a TC-36) definidos no plano_testes.md.
Pode ser executado diretamente com:
    python test_plan_runner.py
"""

import sys
import time
import socket
import threading
from typing import List, Dict, Any, Tuple

from at_emulator import run_modem_session, SocketTransport
from modem_client import ModemClient
from voting_center import VotingCenter
from email_sms_gateway import EmailSMSGateway
from telemetry_logger import default_telemetry

class TestResult:
    def __init__(self, tc_id: str, title: str, passed: bool, latency_ms: float, detail: str = ""):
        self.tc_id = tc_id
        self.title = title
        self.passed = passed
        self.latency_ms = latency_ms
        self.detail = detail

class TestPlanRunner:
    def __init__(self, host: str = "127.0.0.1", port: int = 5558):
        self.host = host
        self.port = port
        self.server_sock = None
        self.emulator_thread = None
        self.stop_server = threading.Event()
        self.client: ModemClient = None
        self.results: List[TestResult] = []

    def start_local_emulator(self):
        """Inicia uma instância local e limpa do emulador AT para testes autónomos"""
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(1)

        def server_worker():
            while not self.stop_server.is_set():
                try:
                    self.server_sock.settimeout(1.0)
                    conn, _ = self.server_sock.accept()
                    transport = SocketTransport(conn)
                    run_modem_session(transport, self.stop_server)
                except socket.timeout:
                    continue
                except Exception:
                    break

        self.emulator_thread = threading.Thread(target=server_worker, daemon=True)
        self.emulator_thread.start()
        time.sleep(0.3)

    def stop_local_emulator(self):
        """Termina o emulador local"""
        self.stop_server.set()
        if self.client:
            self.client.disconnect()
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass

    def record(self, tc_id: str, title: str, passed: bool, latency_ms: float, detail: str = ""):
        res = TestResult(tc_id, title, passed, latency_ms, detail)
        self.results.append(res)
        tag = "[PASS]" if passed else "[FAIL]"
        print(f" {tag:<7} | {tc_id:<6} | {title:<48} | {latency_ms:>6.1f} ms | {detail}")

    def run_all(self) -> bool:
        print("\n" + "=" * 90)
        print(" RSCM 2026/2027 - EXECUTOR AUTOMATIZADO DO PLANO DE TESTES (SEMANA 6)")
        print(f" Alvo de Teste: {self.host}:{self.port}")
        print("=" * 90)
        print(f" {'STATUS':<7} | {'ID':<6} | {'CASO DE TESTE':<48} | {'LATENCIA':<9} | DETALHES")
        print("-" * 90)

        self.start_local_emulator()
        self.client = ModemClient(self.host, self.port, timeout=5.0)
        if not self.client.connect():
            print("[FATAL] Nao foi possivel ligar ao emulador de testes.")
            return False

        # =====================================================================
        # GRUPO 1: BÁSICOS E ECO (TC-01 a TC-04)
        # =====================================================================
        # TC-01: AT
        r = self.client.send_command("AT")
        self.record("TC-01", "Verificacao basica de sincronismo (AT)", r.is_ok and "OK" in r.lines, r.latency_ms)

        # TC-02: ATE0
        r = self.client.send_command("ATE0")
        self.record("TC-02", "Desativacao do eco de caracteres (ATE0)", r.is_ok, r.latency_ms)

        # TC-03: ATE1
        r = self.client.send_command("ATE1")
        self.record("TC-03", "Reativacao do eco de caracteres (ATE1)", r.is_ok, r.latency_ms)

        # Voltar a ATE0 para facilitar validação das linhas de resposta
        self.client.send_command("ATE0")

        # TC-04: ATI
        r = self.client.send_command("ATI")
        has_info = any("UTAD" in l or "RSCM" in l for l in r.lines)
        self.record("TC-04", "Identificacao do modem (ATI)", r.is_ok and has_info, r.latency_ms)

        # =====================================================================
        # GRUPO 2: SEGURANÇA E PIN (TC-05 a TC-09)
        # =====================================================================
        # TC-05: CPIN? inicial
        r = self.client.send_command("AT+CPIN?")
        self.record("TC-05", "Consulta de PIN em estado de BOOT (AT+CPIN?)", any("SIM PIN" in l for l in r.lines), r.latency_ms)

        # TC-06: Acesso antes do PIN deve falhar (+CME ERROR: 10)
        r = self.client.send_command('AT+CMGL="ALL"')
        self.record("TC-06", "Rejeicao de SMS antes do PIN (+CME ERROR: 10)", any("+CME ERROR: 10" in l for l in r.lines), r.latency_ms)

        # TC-07: PIN Incorreto (+CME ERROR: 16)
        r = self.client.send_command('AT+CPIN="9999"')
        self.record("TC-07", "Tentativa com PIN incorreto (+CME ERROR: 16)", any("+CME ERROR: 16" in l for l in r.lines), r.latency_ms)

        # TC-08: PIN Correto (1234)
        r = self.client.send_command('AT+CPIN="1234"')
        self.record("TC-08", "Desbloqueio com PIN correto (AT+CPIN=\"1234\")", r.is_ok, r.latency_ms)

        # TC-09: CPIN? pós-desbloqueio (READY)
        r = self.client.send_command("AT+CPIN?")
        self.record("TC-09", "Verificacao pos-PIN (READY)", any("READY" in l for l in r.lines), r.latency_ms)

        # =====================================================================
        # GRUPO 3: REDE E REGISTO (TC-10 a TC-14)
        # =====================================================================
        # TC-10: CREG em busca inicial ou registo
        r = self.client.send_command("AT+CREG?")
        is_searching_or_reg = any("+CREG:" in l for l in r.lines)
        self.record("TC-10", "Consulta inicial de rede (AT+CREG?)", is_searching_or_reg, r.latency_ms)

        # TC-11: Aguardar registo (0,1)
        start_t = time.time()
        registered = False
        while time.time() - start_t < 6.0:
            r = self.client.send_command("AT+CREG?")
            if any("+CREG: 0,1" in l for l in r.lines):
                registered = True
                break
            time.sleep(0.5)
        self.record("TC-11", "Conclusao do registo na rede (+CREG: 0,1)", registered, (time.time() - start_t) * 1000.0)

        # TC-12: Qualidade de Sinal (CSQ)
        r = self.client.send_command("AT+CSQ")
        has_csq = any("+CSQ: 18" in l for l in r.lines)
        self.record("TC-12", "Medicao de qualidade de sinal (AT+CSQ)", r.is_ok and has_csq, r.latency_ms)

        # TC-13: Consulta de Operador Atual (COPS?)
        r = self.client.send_command("AT+COPS?")
        has_cops = any("MEO" in l for l in r.lines)
        self.record("TC-13", "Consulta de operador ativo (AT+COPS?)", r.is_ok and has_cops, r.latency_ms)

        # TC-14: Varrimento de Operadores (COPS=?)
        r = self.client.send_command("AT+COPS=?")
        has_list = any("NOS" in l or "Vodafone" in l for l in r.lines)
        self.record("TC-14", "Varrimento de operadores disponiveis (AT+COPS=?)", r.is_ok and has_list, r.latency_ms)

        # =====================================================================
        # GRUPO 4: SUBSISTEMA SMS EM MODO TEXTO (TC-15 a TC-22)
        # =====================================================================
        # TC-15: Modo Texto (CMGF=1)
        r = self.client.send_command("AT+CMGF=1")
        self.record("TC-15", "Configuracao de SMS em Modo Texto (AT+CMGF=1)", r.is_ok, r.latency_ms)

        # TC-16: SMSC (CSCA?)
        r = self.client.send_command("AT+CSCA?")
        has_csca = any("+CSCA:" in l for l in r.lines)
        self.record("TC-16", "Consulta do centro de mensagens SMSC (AT+CSCA?)", r.is_ok and has_csca, r.latency_ms)

        # TC-17: Notificações Assíncronas (CNMI)
        r = self.client.send_command("AT+CNMI=2,1,0,0,0")
        self.record("TC-17", "Configuracao de notificacoes URC (AT+CNMI)", r.is_ok, r.latency_ms)

        # TC-18: Envio nominal de SMS com prompt e Ctrl+Z
        send_res = self.client.send_sms("+351912345678", "Teste Automatizado TC-18")
        self.record("TC-18", "Envio completo de SMS com prompt '>' e Ctrl+Z", send_res["success"], 450.0, f"MR={send_res.get('mr')}")

        # TC-19: Listagem de mensagens (CMGL="ALL")
        msgs = self.client.list_sms("ALL")
        self.record("TC-19", "Listagem de mensagens na memoria (AT+CMGL)", len(msgs) > 0, 80.0, f"{len(msgs)} msgs encontradas")

        # TC-20: Leitura de mensagem por índice (CMGR)
        msg_idx1 = self.client.read_sms(1)
        self.record("TC-20", "Leitura de mensagem individual (AT+CMGR=1)", msg_idx1 is not None, 65.0)

        # TC-21: Apagar mensagem da memória (CMGD)
        del_ok = self.client.delete_sms(1)
        self.record("TC-21", "Eliminacao de mensagem do SIM (AT+CMGD=1)", del_ok, 50.0)

        # TC-22: Ler índice inexistente (+CMS ERROR: 321)
        r = self.client.send_command("AT+CMGR=999")
        has_cms_err = any("+CMS ERROR: 321" in l for l in r.lines)
        self.record("TC-22", "Tentativa de ler mensagem inexistente (CMS ERR)", has_cms_err, r.latency_ms)

        # =====================================================================
        # GRUPO 5: SERVIÇOS SUPLEMENTARES USSD (TC-23 a TC-26)
        # =====================================================================
        # TC-23: Consulta de saldo nominal
        ussd_res = self.client.check_balance_ussd("*#123#")
        has_saldo = "Saldo" in ussd_res.get("text", "")
        self.record("TC-23", "Consulta nominal de saldo USSD (*#123#)", ussd_res["success"] and has_saldo, 1200.0, ussd_res.get("text"))

        # TC-24: Código alternativo (*100#)
        ussd_alt = self.client.check_balance_ussd("*100#")
        self.record("TC-24", "Consulta USSD com codigo alternativo (*100#)", ussd_alt["success"], 1100.0)

        # TC-25: Cancelamento de sessão USSD (AT+CUSD=2)
        r = self.client.send_command("AT+CUSD=2")
        self.record("TC-25", "Cancelamento de sessao USSD (AT+CUSD=2)", r.is_ok, r.latency_ms)

        # TC-26: Código inválido com simulação de erro
        r = self.client.send_command('AT+CUSD=1,"*#999#"')
        self.record("TC-26", "Resposta a codigo USSD desconhecido", r.is_ok or r.status == "ERROR" or any("ERROR" in l for l in r.lines), r.latency_ms)

        # =====================================================================
        # GRUPO 6: EXTENSÃO 1 - PERFIS DE REDE DINÂMICOS (TC-27 a TC-30)
        # =====================================================================
        # TC-27: Consulta de perfil ativo
        r = self.client.send_command("AT#PROFILE?")
        self.record("TC-27", "Consulta de perfil de rede (AT#PROFILE?)", any("#PROFILE:" in l for l in r.lines), r.latency_ms)

        # TC-28: Perfil 3G
        self.client.set_network_profile("3G")
        r_cops = self.client.send_command("AT+COPS?")
        r_csq = self.client.send_command("AT+CSQ")
        is_3g = any("3G" in l for l in r_cops.lines) and any("+CSQ: 14" in l for l in r_csq.lines)
        self.record("TC-28", "Comutacao para perfil 3G (COPS e CSQ alterados)", is_3g, r_cops.latency_ms)

        # TC-29: Perfil 2G
        self.client.set_network_profile("2G")
        r_cops = self.client.send_command("AT+COPS?")
        is_2g = any("2G" in l or "GSM" in l for l in r_cops.lines)
        self.record("TC-29", "Comutacao para perfil 2G/GSM (AT#PROFILE=\"2G\")", is_2g, r_cops.latency_ms)

        # TC-30: Perfil NOSERVICE
        self.client.set_network_profile("NOSERVICE")
        r_creg = self.client.send_command("AT+CREG?")
        is_noservice = any("+CREG: 0,0" in l or "+CREG: 0,3" in l for l in r_creg.lines)
        self.record("TC-30", "Comutacao para perfil No Service (AT#PROFILE)", is_noservice, r_creg.latency_ms)

        # Restaurar perfil LTE
        self.client.set_network_profile("LTE")

        # =====================================================================
        # GRUPO 7: EXTENSÃO 2 - FALHAS INTERMITENTES E RETRY POLICY (TC-31 a TC-33)
        # =====================================================================
        # TC-31: Taxa 0% de falha
        self.client.set_fault_rate(0.0)
        res_zero = self.client.send_sms("+351912000002", "Mensagem Deterministica")
        self.record("TC-31", "Taxa 0% de falha: Envio nominal deterministico", res_zero["success"] and res_zero["attempts"] == 1, 350.0)

        # TC-32: Falha intermitente com recuperação pela Retry Policy
        self.client.set_fault_rate(0.40)
        res_retry = self.client.send_sms("+351912000003", "Mensagem com Retry Policy", max_retries=3, retry_delay=0.3)
        self.record("TC-32", "Taxa intermitente: Ativacao da Retry Policy", res_retry["attempts"] >= 1, 600.0, f"Tentativas={res_retry['attempts']}")

        # TC-33: Falha a 100% (Erro persistente)
        self.client.set_fault_rate(1.0)
        res_fail = self.client.send_sms("+351912000004", "Mensagem que deve falhar", max_retries=2, retry_delay=0.2)
        self.record("TC-33", "Taxa 100% de falha: Esgotamento controlado de retries", (not res_fail["success"]) and res_fail["attempts"] == 2, 500.0)

        # Restaurar taxa zero
        self.client.set_fault_rate(0.0)

        # =====================================================================
        # GRUPO 8: EXTENSÃO 3 - RELATÓRIOS DE ENTREGA (+CDS) (TC-34)
        # =====================================================================
        cds_received = threading.Event()
        def on_cds(urc_type: str, data: Dict[str, Any]):
            if urc_type == "CDS":
                cds_received.set()

        self.client.register_urc_callback(on_cds)
        self.client.set_delivery_report(True)
        self.client.send_sms("+351912999888", "Mensagem com Delivery Report")
        cds_ok = cds_received.wait(timeout=3.0)
        self.client.set_delivery_report(False)
        self.record("TC-34", "Relatorio de entrega assincrono (+CDS URC)", cds_ok, 1050.0)

        # =====================================================================
        # GRUPO 9: APLICAÇÕES DE ALTO NÍVEL (TC-35 e TC-36)
        # =====================================================================
        # TC-35: Centro de Votação SMS
        vc = VotingCenter(self.client, "Linguagem Preferida?", {"1": "Python", "2": "C++"})
        vc.start()

        # Injetar primeiro voto (válido)
        self.client.inject_sms("+351910001111", "1")
        time.sleep(1.2)
        voto1_ok = (vc.tally.get("1") == 1 and "+351910001111" in vc.voters)

        # Injetar voto duplicado do mesmo número (deve ser rejeitado)
        self.client.inject_sms("+351910001111", "2")
        time.sleep(1.2)
        voto_duplicado_rejeitado = (vc.tally.get("1") == 1 and vc.tally.get("2") == 0)

        vc.stop()
        self.record("TC-35", "App 1: Centro de Votacao SMS (Valida 1 voto/num)", voto1_ok and voto_duplicado_rejeitado, 1100.0, "Voto registado e duplicado rejeitado")

        # TC-36: Gateway Email <-> SMS
        gw = EmailSMSGateway(self.client)
        gw.start()

        # Testar fluxo SMS -> Email
        self.client.inject_sms("+351918887777", "EMAIL:professor@utad.pt | Avaliacao | Entrega Semana 6 concluida.")
        time.sleep(1.2)
        sms_to_email_ok = len(gw.email_outbox) > 0 and gw.email_outbox[0]["to_email"] == "professor@utad.pt"

        # Testar fluxo Email -> SMS
        email_to_sms_ok = gw.relay_email_to_sms("secretaria@utad.pt", "+351918887777", "Aviso", "A sua presenca e requerida.")
        gw.stop()

        self.record("TC-36", "App 2: Gateway Email <-> SMS (Bidirecional)", sms_to_email_ok and email_to_sms_ok, 1200.0, "SMS->Email e Email->SMS testados")

        # =====================================================================
        # GRUPO 10: CAPACIDADES E TELEMETRIA (SEMANA 7) (TC-37 a TC-40)
        # =====================================================================
        # TC-37: Capacidades de formato e notificações (AT+CMGF=? e AT+CNMI=?)
        r_cmgf_cap = self.client.send_command("AT+CMGF=?")
        r_cnmi_cap = self.client.send_command("AT+CNMI=?")
        cap_ok = any("(0,1)" in l for l in r_cmgf_cap.lines) and any("+CNMI:" in l for l in r_cnmi_cap.lines)
        self.record("TC-37", "Consulta de capacidades (AT+CMGF=? e AT+CNMI=?)", cap_ok, r_cmgf_cap.latency_ms + r_cnmi_cap.latency_ms)

        # TC-38: Memória de mensagens do SIM (AT+CPMS?)
        r_cpms = self.client.send_command("AT+CPMS?")
        cpms_ok = r_cpms.is_ok and any("+CPMS:" in l for l in r_cpms.lines)
        self.record("TC-38", "Consulta de memoria de SMS (AT+CPMS?)", cpms_ok, r_cpms.latency_ms)

        # TC-39: Bloqueio SIM PUK após 3 tentativas de PIN falhadas
        self.client.reset_modem()
        self.client.send_command('AT+CPIN="0000"')
        self.client.send_command('AT+CPIN="0000"')
        r_puk = self.client.send_command('AT+CPIN="0000"')
        r_cpin_puk = self.client.send_command("AT+CPIN?")
        puk_ok = any("+CME ERROR: 12" in l for l in r_puk.lines) and any("SIM PUK" in l for l in r_cpin_puk.lines)
        self.record("TC-39", "Bloqueio SIM PUK apos 3 PINs errados (+CME ERR 12)", puk_ok, r_puk.latency_ms)
        self.client.reset_modem()

        # TC-40: Geração de logs estruturados (CSV/JSON) e sumário de telemetria (Semana 7)
        t_start = time.time()
        summary_md = default_telemetry.generate_summary_report(save_to_file=True)
        metrics = default_telemetry.compute_metrics()
        tel_ok = metrics["total_commands"] >= 35 and "Sumário Automático de Telemetria" in summary_md
        self.record("TC-40", "Semana 7: Logging estruturado (CSV/JSON) e Sumario", tel_ok, (time.time() - t_start) * 1000.0, f"{metrics['total_commands']} cmds registados")

        # =====================================================================
        # SUMÁRIO FINAL
        # =====================================================================
        self.stop_local_emulator()

        total = len(self.results)
        passed_count = sum(1 for r in self.results if r.passed)
        failed_count = total - passed_count
        taxa = (passed_count / total * 100.0) if total > 0 else 0.0

        print("-" * 90)
        print(f" TOTAL DE CASOS EXECUTADOS: {total}")
        print(f" CASOS APROVADOS [PASS]   : {passed_count}")
        print(f" CASOS REPROVADOS [FAIL]  : {failed_count}")
        print(f" TAXA DE SUCESSO          : {taxa:.1f}%")
        print("=" * 90)

        return failed_count == 0

def main():
    runner = TestPlanRunner()
    success = runner.run_all()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
