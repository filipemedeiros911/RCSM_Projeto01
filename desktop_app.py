"""
Interface Desktop de Controlo de Ordens, Aplicações e Telemetria (Semanas 1–7)
Disciplina: Redes e Serviços de Comunicações Móveis (RSCM) — 2026/2027
Universidade de Trás-os-Montes e Alto Douro (UTAD)

Conceito:
O utilizador emite todas as ordens a partir desta interface gráfica (Desktop UI),
quer manualmente (escrevendo comandos AT na consola), quer através dos painéis de controlo.
Se o emulador AT (at_emulator.py) ainda não estiver aberto num terminal externo quando se
liga por TCP (127.0.0.1:5555), a própria interface inicia-o automaticamente em background
para garantir funcionamento imediato.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import queue
import time
from typing import Optional

from modem_client import ModemClient, ATResponse
from at_emulator import run_server, run_serial, HOST, PORT
from voting_center import VotingCenter
from email_sms_gateway import EmailSMSGateway
from telemetry_logger import default_telemetry


class DesktopOrderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("RSCM 2026/2027 - Painel de Ordens, Aplicacoes e Telemetria do Modem AT")
        self.root.geometry("1160x820")
        self.root.minsize(980, 700)

        # Cliente do Modem e Emulador Embutido (fallback automático)
        self.client: Optional[ModemClient] = None
        self.is_connected = False
        self._embedded_emu_stop = threading.Event()
        self._embedded_emu_thread: Optional[threading.Thread] = None

        # Instâncias das aplicações de alto nível (Semana 6)
        self.voting_center: Optional[VotingCenter] = None
        self.email_gateway: Optional[EmailSMSGateway] = None

        # Fila de eventos para atualizar a UI a partir de threads secundárias
        self.ui_queue = queue.Queue()

        # Configurar estilos e layout
        self._configure_styles()
        self._create_widgets()

        # Loop de processamento de eventos da UI
        self.root.after(100, self._process_ui_queue)

        # Ligar automaticamente ao abrir para que os comandos funcionem de imediato
        self.root.after(300, self._auto_connect_on_startup)

    def _detect_default_connection(self):
        """Usa COM5 se existir no sistema; caso contrário usa TCP 127.0.0.1:5555 por omissão."""
        try:
            import serial.tools.list_ports
            ports = [p.device.upper() for p in serial.tools.list_ports.comports()]
            if "COM5" in ports:
                return "COM5", "9600"
        except Exception:
            pass
        return HOST, str(PORT)

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), foreground="#1e293b")
        style.configure("SubHeader.TLabel", font=("Segoe UI", 9, "bold"), foreground="#334155")
        style.configure("Status.TLabel", font=("Segoe UI", 9, "italic"), foreground="#475569")
        style.configure("Action.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("Danger.TButton", foreground="#b91c1c")

    def _create_widgets(self):
        main_paned = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # -------------------------------------------------------------
        # 1. PARTE SUPERIOR: ORDENS E PAINÉIS DO UTILIZADOR
        # -------------------------------------------------------------
        top_frame = ttk.Frame(main_paned)
        main_paned.add(top_frame, weight=3)

        # 1.1 Barra Superior: Ligação ao Setup / Emulador
        conn_group = ttk.LabelFrame(top_frame, text=" 1. Ligacao ao Setup / Emulador (com0com ou TCP) ", padding=8)
        conn_group.pack(fill=tk.X, padx=4, pady=4)

        default_host, default_port = self._detect_default_connection()

        ttk.Label(conn_group, text="Modo/Alvo:").pack(side=tk.LEFT, padx=4)
        self.conn_mode_var = tk.StringVar(value=default_host)
        self.conn_entry = ttk.Entry(conn_group, textvariable=self.conn_mode_var, width=14)
        self.conn_entry.pack(side=tk.LEFT, padx=4)

        ttk.Label(conn_group, text="Baud/Port:").pack(side=tk.LEFT, padx=4)
        self.baud_var = tk.StringVar(value=default_port)
        self.baud_entry = ttk.Entry(conn_group, textvariable=self.baud_var, width=8)
        self.baud_entry.pack(side=tk.LEFT, padx=4)

        self.btn_connect = ttk.Button(conn_group, text="Conectar ao Modem", command=self._toggle_connection)
        self.btn_connect.pack(side=tk.LEFT, padx=8)

        self.lbl_status = ttk.Label(conn_group, text="[DESCONECTADO]", foreground="#b91c1c", font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=8)

        # Atalhos rápidos de porta
        ttk.Button(conn_group, text="Usar COM5 (Setup com0com)", command=lambda: self._set_conn_mode("COM5", "9600")).pack(side=tk.RIGHT, padx=4)
        ttk.Button(conn_group, text="Usar TCP (127.0.0.1:5555)", command=lambda: self._set_conn_mode("127.0.0.1", "5555")).pack(side=tk.RIGHT, padx=4)

        # 1.2 Separadores com Categorias de Ordens
        self.notebook = ttk.Notebook(top_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Tab A: Ordens de Arranque e Diagnóstico
        tab_setup = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_setup, text="  1. Setup & Rede  ")
        self._build_setup_tab(tab_setup)

        # Tab B: Ordens de Envio de Mensagens SMS
        tab_sms = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_sms, text="  2. Envio de SMS  ")
        self._build_sms_tab(tab_sms)

        # Tab C: Caixa de Entrada e Injeção de Testes
        tab_inbox = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_inbox, text="  3. Caixa de Entrada & Injetor  ")
        self._build_inbox_tab(tab_inbox)

        # Tab D: Perfis de Rede, Falhas e Relatórios de Entrega (CDS)
        tab_ext = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_ext, text="  4. Perfis, Falhas & Entrega  ")
        self._build_extensions_tab(tab_ext)

        # Tab E: Aplicações de Alto Nível (Votação SMS & Gateway Email)
        tab_apps = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_apps, text="  5. Apps Alto Nivel (Votacao / Gateway)  ")
        self._build_apps_tab(tab_apps)

        # Tab F: Registo e Telemetria
        tab_tel = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_tel, text="  6. Telemetria & Logs  ")
        self._build_telemetry_tab(tab_tel)

        # -------------------------------------------------------------
        # 2. PARTE INFERIOR: CONSOLA DE ORDENS E MONITORIZAÇÃO (TERMINAL)
        # -------------------------------------------------------------
        bot_frame = ttk.Frame(main_paned)
        main_paned.add(bot_frame, weight=2)

        bot_label_frame = ttk.LabelFrame(
            bot_frame,
            text=" Consola Interativa AT: Escreva o comando na barra abaixo (ou clique num comando) e prima Enter ",
            padding=6
        )
        bot_label_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Barra de Comando Manual (Raw AT)
        cmd_bar = ttk.Frame(bot_label_frame)
        cmd_bar.pack(fill=tk.X, pady=(0, 6))

        self.lbl_manual_prompt = ttk.Label(cmd_bar, text="Ordem AT Manual:", font=("Segoe UI", 9, "bold"))
        self.lbl_manual_prompt.pack(side=tk.LEFT, padx=4)

        self.raw_cmd_var = tk.StringVar(value="AT")
        self.raw_entry = ttk.Entry(cmd_bar, textvariable=self.raw_cmd_var, font=("Consolas", 10))
        self.raw_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.raw_entry.bind("<Return>", lambda e: self._send_raw_order())
        self.raw_entry.bind("<Escape>", lambda e: self._cancel_sms_prompt_if_active())

        # Lista rápida de comandos para ajudar a testar manualmente
        quick_cmds = [
            "AT",
            "ATI",
            "ATE0",
            "AT+CPIN?",
            'AT+CPIN="1234"',
            "AT+CREG?",
            "AT+CSQ",
            "AT+COPS?",
            "AT+CMGF=1",
            "AT+CNMI=2,1,0,0,0",
            "AT+CPMS?",
            'AT+CMGL="ALL"',
            "AT+CMGR=1",
            'AT+CMGS="+351912345678"',
            'AT+CUSD=1,"*#123#"',
            "AT#PROFILE?",
            "AT#RESET"
        ]
        self.quick_cb = ttk.Combobox(cmd_bar, values=quick_cmds, width=22, state="readonly")
        self.quick_cb.set("Exemplos de Comandos...")
        self.quick_cb.pack(side=tk.LEFT, padx=4)
        self.quick_cb.bind("<<ComboboxSelected>>", self._on_quick_cmd_selected)

        btn_send_raw = ttk.Button(cmd_bar, text="Executar Ordem (Enter)", style="Action.TButton", command=self._send_raw_order)
        btn_send_raw.pack(side=tk.LEFT, padx=4)

        btn_clear_log = ttk.Button(cmd_bar, text="Limpar Consola", command=self._clear_console)
        btn_clear_log.pack(side=tk.RIGHT, padx=4)

        # Consola de Texto com Scroll e Cores (Bloqueada contra edição acidental e redireciona escrita para a barra!)
        self.console = scrolledtext.ScrolledText(
            bot_label_frame,
            wrap=tk.WORD,
            height=10,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#f8fafc",
            state=tk.DISABLED
        )
        self.console.pack(fill=tk.BOTH, expand=True)
        self.console.bind("<Key>", self._redirect_console_key_to_entry)

        # Configurar tags de cor para a consola
        self.console.tag_config("TX", foreground="#38bdf8")      # Azul claro (Ordens enviadas)
        self.console.tag_config("RX_OK", foreground="#4ade80")   # Verde (Respostas OK)
        self.console.tag_config("RX_ERR", foreground="#f87171")  # Vermelho (Erros)
        self.console.tag_config("URC", foreground="#fbbf24")     # Amarelo/Ouro (Eventos assíncronos)
        self.console.tag_config("INFO", foreground="#94a3b8")    # Cinzento (Informação)

    def _on_quick_cmd_selected(self, _event=None):
        val = self.quick_cb.get()
        if val and not val.startswith("Exemplos"):
            self.raw_cmd_var.set(val)
            self.raw_entry.focus_set()
            self.raw_entry.icursor(tk.END)

    def _redirect_console_key_to_entry(self, event):
        """Se o utilizador clicar na consola preta e começar a escrever, redireciona para a barra de comandos."""
        if event.state & 0x4:  # Permitir Ctrl+C para copiar texto da consola
            return
        self.raw_entry.focus_set()
        if event.keysym == "Return":
            self._send_raw_order()
            return "break"
        elif event.keysym == "BackSpace":
            cur = self.raw_cmd_var.get()
            self.raw_cmd_var.set(cur[:-1])
            self.raw_entry.icursor(tk.END)
            return "break"
        elif event.char and event.char.isprintable():
            self.raw_cmd_var.set(self.raw_cmd_var.get() + event.char)
            self.raw_entry.icursor(tk.END)
            return "break"

    # -------------------------------------------------------------
    # Construtores das Abas
    # -------------------------------------------------------------

    def _build_setup_tab(self, parent: ttk.Frame):
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.BOTH, expand=True)

        # Coluna 1: Ordens Automáticas
        col1 = ttk.LabelFrame(grid, text=" Ordens de Inicializacao ", padding=8)
        col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        btn_init = ttk.Button(
            col1,
            text="Dar Ordem: Inicializacao Completa (Auto)",
            style="Action.TButton",
            command=self._order_full_init
        )
        btn_init.pack(fill=tk.X, pady=6)
        ttk.Label(
            col1,
            text="Executa: ATE0 -> CMEE=1 -> PIN 1234 -> Registo (4s) -> CMGF=1 -> CNMI",
            font=("Segoe UI", 8),
            foreground="#64748b"
        ).pack(anchor=tk.W)

        ttk.Separator(col1, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        pin_frame = ttk.Frame(col1)
        pin_frame.pack(fill=tk.X, pady=4)
        ttk.Label(pin_frame, text="PIN do SIM:").pack(side=tk.LEFT)
        self.pin_var = tk.StringVar(value="1234")
        ttk.Entry(pin_frame, textvariable=self.pin_var, width=8).pack(side=tk.LEFT, padx=6)
        ttk.Button(pin_frame, text="Dar Ordem: Desbloquear PIN", command=self._order_unlock_pin).pack(side=tk.LEFT)

        ttk.Button(col1, text="Consultar Estado do PIN (AT+CPIN?)", command=lambda: self._dispatch_cmd("AT+CPIN?")).pack(fill=tk.X, pady=4)

        # Coluna 2: Ordens de Diagnóstico e Rede
        col2 = ttk.LabelFrame(grid, text=" Ordens de Diagnostico e Rede ", padding=8)
        col2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Button(col2, text="Consultar Sinal (AT+CSQ)", command=lambda: self._dispatch_cmd("AT+CSQ")).pack(fill=tk.X, pady=3)
        ttk.Button(col2, text="Consultar Registo na Rede (AT+CREG?)", command=lambda: self._dispatch_cmd("AT+CREG?")).pack(fill=tk.X, pady=3)
        ttk.Button(col2, text="Consultar Operador Atual (AT+COPS?)", command=lambda: self._dispatch_cmd("AT+COPS?")).pack(fill=tk.X, pady=3)
        ttk.Button(col2, text="Consultar Memoria SIM (AT+CPMS?)", command=lambda: self._dispatch_cmd("AT+CPMS?")).pack(fill=tk.X, pady=3)

        # Coluna 3: Ordens Suplementares (USSD)
        col3 = ttk.LabelFrame(grid, text=" Ordens de Servicos Suplementares (USSD) ", padding=8)
        col3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        ussd_f = ttk.Frame(col3)
        ussd_f.pack(fill=tk.X, pady=4)
        ttk.Label(ussd_f, text="Codigo USSD:").pack(side=tk.LEFT)
        self.ussd_code_var = tk.StringVar(value="*#123#")
        ttk.Entry(ussd_f, textvariable=self.ussd_code_var, width=12).pack(side=tk.LEFT, padx=4)

        ttk.Button(col3, text="Dar Ordem: Consultar Saldo USSD", style="Action.TButton", command=self._order_ussd).pack(fill=tk.X, pady=4)
        ttk.Button(col3, text="Simular Timeout USSD (*#999#)", command=lambda: self._dispatch_cmd('AT+CUSD=1,"*#999#"')).pack(fill=tk.X, pady=4)
        ttk.Label(
            col3,
            text="Simula envio de pedido a rede com latencia fisica (500-3000ms).",
            font=("Segoe UI", 8),
            foreground="#64748b"
        ).pack(anchor=tk.W)

    def _build_sms_tab(self, parent: ttk.Frame):
        frame = ttk.LabelFrame(parent, text=" Emitir Ordem de Envio de Mensagem SMS ", padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        dest_f = ttk.Frame(frame)
        dest_f.pack(fill=tk.X, pady=4)
        ttk.Label(dest_f, text="Numero Destinatario:").pack(side=tk.LEFT)
        self.sms_dest_var = tk.StringVar(value="+351912345678")
        ttk.Entry(dest_f, textvariable=self.sms_dest_var, width=25).pack(side=tk.LEFT, padx=6)

        ttk.Label(frame, text="Texto da Mensagem (max 160 caracteres):").pack(anchor=tk.W, pady=(6, 2))
        self.sms_text_box = scrolledtext.ScrolledText(frame, height=4, font=("Segoe UI", 10))
        self.sms_text_box.insert(tk.END, "Ola do Painel de Ordens RSCM!")
        self.sms_text_box.pack(fill=tk.X, pady=2)

        ctrl_f = ttk.Frame(frame)
        ctrl_f.pack(fill=tk.X, pady=6)

        ttk.Label(ctrl_f, text="Politica de Retry (Tentativas em Falha):").pack(side=tk.LEFT)
        self.retry_count_var = tk.IntVar(value=3)
        ttk.Spinbox(ctrl_f, from_=1, to=5, textvariable=self.retry_count_var, width=4).pack(side=tk.LEFT, padx=6)

        btn_send_sms = ttk.Button(
            ctrl_f,
            text="DAR ORDEM DE ENVIO DE SMS",
            style="Action.TButton",
            command=self._order_send_sms
        )
        btn_send_sms.pack(side=tk.RIGHT, padx=6)

    def _build_inbox_tab(self, parent: ttk.Frame):
        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_f = ttk.LabelFrame(paned, text=" Mensagens no SIM (AT+CMGL) ", padding=6)
        paned.add(left_f, weight=3)

        btn_bar = ttk.Frame(left_f)
        btn_bar.pack(fill=tk.X, pady=4)
        ttk.Button(btn_bar, text="Atualizar Caixa (Listar SMS)", command=self._order_list_sms).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="Ler SMS Selecionado (AT+CMGR)", command=self._order_read_selected_sms).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="Apagar SMS Selecionado (AT+CMGD)", style="Danger.TButton", command=self._order_delete_selected_sms).pack(side=tk.LEFT, padx=4)

        columns = ("index", "status", "sender", "timestamp", "text")
        self.inbox_tree = ttk.Treeview(left_f, columns=columns, show="headings", height=7)
        self.inbox_tree.heading("index", text="ID")
        self.inbox_tree.heading("status", text="Estado")
        self.inbox_tree.heading("sender", text="Remetente")
        self.inbox_tree.heading("timestamp", text="Data/Hora")
        self.inbox_tree.heading("text", text="Mensagem")

        self.inbox_tree.column("index", width=40, anchor=tk.CENTER)
        self.inbox_tree.column("status", width=90, anchor=tk.CENTER)
        self.inbox_tree.column("sender", width=120)
        self.inbox_tree.column("timestamp", width=140)
        self.inbox_tree.column("text", width=250)
        self.inbox_tree.pack(fill=tk.BOTH, expand=True)

        right_f = ttk.LabelFrame(paned, text=" Ordem: Injetar SMS na Rede (+CMTI) ", padding=6)
        paned.add(right_f, weight=2)

        ttk.Label(right_f, text="Remetente Simulado:").pack(anchor=tk.W)
        self.inject_sender_var = tk.StringVar(value="+351919999000")
        ttk.Entry(right_f, textvariable=self.inject_sender_var).pack(fill=tk.X, pady=2)

        ttk.Label(right_f, text="Conteudo da Mensagem:").pack(anchor=tk.W, pady=(4, 0))
        self.inject_text_var = tk.StringVar(value="1")
        ttk.Entry(right_f, textvariable=self.inject_text_var).pack(fill=tk.X, pady=2)

        ttk.Button(
            right_f,
            text="Injetar Mensagem na Rede",
            style="Action.TButton",
            command=self._order_inject_sms
        ).pack(fill=tk.X, pady=6)
        ttk.Label(
            right_f,
            text="Dispara o evento assincrono +CMTI imediatamente no emulador.",
            font=("Segoe UI", 8),
            foreground="#64748b"
        ).pack(anchor=tk.W)

    def _build_extensions_tab(self, parent: ttk.Frame):
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.BOTH, expand=True)

        p_frame = ttk.LabelFrame(grid, text=" Perfil de Rede Dinamico ", padding=8)
        p_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Label(p_frame, text="Selecione o Perfil:").pack(anchor=tk.W)
        self.profile_var = tk.StringVar(value="LTE")
        profile_cb = ttk.Combobox(p_frame, textvariable=self.profile_var, values=["LTE", "3G", "2G", "NOSERVICE"], state="readonly")
        profile_cb.pack(fill=tk.X, pady=4)

        ttk.Button(p_frame, text="Dar Ordem: Aplicar Perfil (AT#PROFILE)", command=self._order_set_profile).pack(fill=tk.X, pady=4)
        ttk.Label(p_frame, text="Altera dinamicamente as respostas de +COPS?, +CREG? e +CSQ.", font=("Segoe UI", 8), foreground="#64748b").pack(anchor=tk.W)

        f_frame = ttk.LabelFrame(grid, text=" Simulacao de Falhas Intermitentes ", padding=8)
        f_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Label(f_frame, text="Probabilidade de Erro p (0.0 a 1.0):").pack(anchor=tk.W)
        self.fault_rate_var = tk.DoubleVar(value=0.0)
        self.fault_scale = ttk.Scale(f_frame, from_=0.0, to=1.0, variable=self.fault_rate_var, orient=tk.HORIZONTAL)
        self.fault_scale.pack(fill=tk.X, pady=4)

        self.lbl_fault_val = ttk.Label(f_frame, text="Probabilidade: 0%")
        self.lbl_fault_val.pack(anchor=tk.W)
        self.fault_scale.configure(command=lambda v: self.lbl_fault_val.configure(text=f"Probabilidade: {float(v)*100:.0f}%"))

        ttk.Button(f_frame, text="Dar Ordem: Configurar Taxa (AT#FAULT_RATE)", command=self._order_set_fault).pack(fill=tk.X, pady=4)
        ttk.Label(f_frame, text="Permite testar a robustez da Retry Policy perante falhas temporarias.", font=("Segoe UI", 8), foreground="#64748b").pack(anchor=tk.W)

        r_frame = ttk.LabelFrame(grid, text=" Relatorios de Entrega & Reset ", padding=8)
        r_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.cds_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r_frame, text="Ativar Relatorios de Entrega (+CDS)", variable=self.cds_var, command=self._order_toggle_cds).pack(anchor=tk.W, pady=6)
        ttk.Label(r_frame, text="O modem gera notificacoes +CDS assincronas apos cada envio de SMS.", font=("Segoe UI", 8), foreground="#64748b").pack(anchor=tk.W)

        ttk.Separator(r_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Button(r_frame, text="Dar Ordem: Reset ao Emulador (AT#RESET)", style="Danger.TButton", command=self._order_reset_modem).pack(fill=tk.X, pady=4)

    def _build_apps_tab(self, parent: ttk.Frame):
        """Separador para controlar e demonstrar as 2 Aplicações de Alto Nível (Semana 6)."""
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.BOTH, expand=True)

        # App 1: Centro de Votação por SMS
        v_frame = ttk.LabelFrame(grid, text=" App 1: Centro de Votacao por SMS ", padding=8)
        v_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        btn_v_row = ttk.Frame(v_frame)
        btn_v_row.pack(fill=tk.X, pady=2)
        self.btn_toggle_voting = ttk.Button(btn_v_row, text="Iniciar Centro de Votacao", style="Action.TButton", command=self._toggle_voting_center)
        self.btn_toggle_voting.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_v_row, text="Simular Voto (Opcao 1)", command=lambda: self._simulate_vote("1")).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_v_row, text="Simular Voto (Opcao 2)", command=lambda: self._simulate_vote("2")).pack(side=tk.LEFT, padx=2)

        self.voting_status_box = scrolledtext.ScrolledText(v_frame, height=7, font=("Consolas", 9), bg="#f8fafc")
        self.voting_status_box.pack(fill=tk.BOTH, expand=True, pady=4)
        self.voting_status_box.insert(tk.END, "Centro de Votacao inativo.\nClique em 'Iniciar Centro de Votacao' (requer modem inicializado).")

        # App 2: Gateway Email <-> SMS
        g_frame = ttk.LabelFrame(grid, text=" App 2: Gateway Bidirecional Email <-> SMS ", padding=8)
        g_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        btn_g_row = ttk.Frame(g_frame)
        btn_g_row.pack(fill=tk.X, pady=2)
        self.btn_toggle_gateway = ttk.Button(btn_g_row, text="Iniciar Gateway Email<->SMS", style="Action.TButton", command=self._toggle_email_gateway)
        self.btn_toggle_gateway.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_g_row, text="Simular SMS->Email", command=self._simulate_sms_to_email).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_g_row, text="Simular Email->SMS", command=self._simulate_email_to_sms).pack(side=tk.LEFT, padx=2)

        self.gateway_status_box = scrolledtext.ScrolledText(g_frame, height=7, font=("Consolas", 9), bg="#f8fafc")
        self.gateway_status_box.pack(fill=tk.BOTH, expand=True, pady=4)
        self.gateway_status_box.insert(tk.END, "Gateway Email <-> SMS inativo.\nClique em 'Iniciar Gateway Email<->SMS' (requer modem inicializado).")

    def _build_telemetry_tab(self, parent: ttk.Frame):
        """Separador de Registo Estruturado (CSV/JSON) e Telemetria Automática (Semana 7)."""
        top_bar = ttk.Frame(parent)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(top_bar, text="Atualizar Telemetria & Sumario", style="Action.TButton", command=self._refresh_telemetry_view).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_bar, text="Exportar Relatorio (logs/sumario_telemetria.md)", command=self._export_telemetry_report).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_bar, text="Limpar Registos de Log", style="Danger.TButton", command=self._clear_telemetry_logs).pack(side=tk.RIGHT, padx=4)

        self.lbl_tel_metrics = ttk.Label(
            parent,
            text="Comandos: 0 | SMS Enviados: 0 | SMS Recebidos: 0 | Taxa de Erros: 0.0% | Latencia Media: 0.0 ms",
            font=("Segoe UI", 9, "bold"),
            foreground="#0f172a"
        )
        self.lbl_tel_metrics.pack(anchor=tk.W, padx=4, pady=2)

        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Tabela de Logs Estruturados
        log_frame = ttk.LabelFrame(paned, text=" Registo Estruturado (telemetria_at.csv / .json) ", padding=4)
        paned.add(log_frame, weight=3)

        cols = ("timestamp", "port", "cmd", "response", "state", "latency")
        self.tel_tree = ttk.Treeview(log_frame, columns=cols, show="headings", height=7)
        self.tel_tree.heading("timestamp", text="Timestamp")
        self.tel_tree.heading("port", text="Porta")
        self.tel_tree.heading("cmd", text="Linha AT")
        self.tel_tree.heading("response", text="Resposta")
        self.tel_tree.heading("state", text="Estado Interno")
        self.tel_tree.heading("latency", text="Latência (ms)")

        self.tel_tree.column("timestamp", width=135)
        self.tel_tree.column("port", width=95, anchor=tk.CENTER)
        self.tel_tree.column("cmd", width=130)
        self.tel_tree.column("response", width=180)
        self.tel_tree.column("state", width=110, anchor=tk.CENTER)
        self.tel_tree.column("latency", width=85, anchor=tk.E)
        self.tel_tree.pack(fill=tk.BOTH, expand=True)

        # Sumário por Comando
        sum_frame = ttk.LabelFrame(paned, text=" Sumario de Metricas por Comando ", padding=4)
        paned.add(sum_frame, weight=2)

        self.tel_summary_box = scrolledtext.ScrolledText(sum_frame, height=7, font=("Consolas", 9), bg="#f8fafc")
        self.tel_summary_box.pack(fill=tk.BOTH, expand=True)

    # -------------------------------------------------------------
    # Gestão de Ligação e Auto-Arranque do Emulador
    # -------------------------------------------------------------

    def _set_conn_mode(self, port_or_host: str, baud_or_port: str):
        self.conn_mode_var.set(port_or_host)
        self.baud_var.set(baud_or_port)

    def _ensure_local_tcp_emulator(self, host: str, port: int):
        """Se o modo for TCP local e o at_emulator.py não estiver a correr lá fora, inicia-o em background."""
        if host not in ("127.0.0.1", "localhost"):
            return
        import socket
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(0.25)
        try:
            test_sock.connect((host, port))
            test_sock.close()
            return  # Já existe um emulador ativo nessa porta
        except Exception:
            try:
                test_sock.close()
            except Exception:
                pass

        if self._embedded_emu_thread is None or not self._embedded_emu_thread.is_alive():
            self._embedded_emu_stop.clear()
            self._embedded_emu_thread = threading.Thread(
                target=run_server,
                args=(host, port, self._embedded_emu_stop),
                daemon=True
            )
            self._embedded_emu_thread.start()
            self._log_info(f"Emulador AT iniciado automaticamente em background ({host}:{port}).")
            time.sleep(0.25)

    def _ensure_local_serial_emulator(self, client_port: str, baudrate: int):
        """Se o cliente ligar a COM5 e nenhuma instância externa estiver em COM6, arranca o emulador em COM6."""
        pair_port = "COM6" if client_port.upper() == "COM5" else ("COM5" if client_port.upper() == "COM6" else "COM6")
        import socket
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(0.2)
        try:
            test_sock.connect(("127.0.0.1", 5556))
            test_sock.close()
            return  # Já existe um emulador série a correr (ex: num terminal externo)
        except Exception:
            try:
                test_sock.close()
            except Exception:
                pass

        if getattr(self, "_embedded_serial_thread", None) is None or not self._embedded_serial_thread.is_alive():
            self._embedded_serial_stop = threading.Event()
            self._embedded_serial_thread = threading.Thread(
                target=run_serial,
                args=(pair_port, baudrate, self._embedded_serial_stop),
                daemon=True
            )
            self._embedded_serial_thread.start()
            self._log_info(f"Emulador AT iniciado automaticamente na porta par {pair_port} ({baudrate} bps).")
            time.sleep(0.3)

    def _auto_connect_on_startup(self):
        if not self.is_connected:
            self._toggle_connection(silent_on_error=True)

    def _toggle_connection(self, silent_on_error: bool = False):
        if self.is_connected:
            if self.voting_center and self.voting_center.is_active:
                self.voting_center.stop()
            if self.email_gateway and self.email_gateway.is_active:
                self.email_gateway.stop()
            if self.client:
                self.client.disconnect()
            self.is_connected = False
            self.lbl_status.configure(text="[DESCONECTADO]", foreground="#b91c1c")
            self.btn_connect.configure(text="Conectar ao Modem")
            self._log_info("Desconectado do modem.")
        else:
            target = self.conn_mode_var.get().strip()
            try:
                baud_or_p = int(self.baud_var.get().strip())
            except ValueError:
                baud_or_p = 5555

            if not target.upper().startswith("COM"):
                self._ensure_local_tcp_emulator(target, baud_or_p)
            else:
                self._ensure_local_serial_emulator(target, baud_or_p)

            self._log_info(f"A estabelecer ligacao a {target}:{baud_or_p}...")
            self.client = ModemClient(target, baud_or_p)
            self.client.register_urc_callback(self._on_urc_received)

            if self.client.connect():
                self.is_connected = True
                self.lbl_status.configure(text=f"[CONECTADO: {target}:{baud_or_p}]", foreground="#15803d")
                self.btn_connect.configure(text="Desconectar")
                self._log_info(
                    f"Ligacao estabelecida com sucesso a {target}:{baud_or_p}! "
                    "Pode usar os botoes acima ou escrever comandos AT na barra abaixo (ex: AT, AT+CPIN=\"1234\")."
                )
                self._refresh_telemetry_view()
            else:
                self.lbl_status.configure(text="[ERRO DE LIGACAO]", foreground="#b91c1c")
                self._log_error(f"Falha ao ligar a {target}:{baud_or_p}. Clique em 'Usar TCP (127.0.0.1:5555)' e tente novamente.")
                if not silent_on_error:
                    messagebox.showerror(
                        "Erro de Ligacao",
                        f"Nao foi possivel ligar a {target}:{baud_or_p}.\n\n"
                        "Dica: Clique no botao 'Usar TCP (127.0.0.1:5555)' no canto superior direito e clique em 'Conectar ao Modem'."
                    )

    def _on_urc_received(self, urc_type: str, data: dict):
        self.ui_queue.put(("URC", urc_type, data))

    # -------------------------------------------------------------
    # Emissão de Ordens (Executadas em Background Thread)
    # -------------------------------------------------------------

    def _run_in_background(self, task_func):
        if not self.is_connected or not self.client:
            self._toggle_connection(silent_on_error=True)
            if not self.is_connected or not self.client:
                messagebox.showwarning("Aviso", "O modem nao esta conectado. Clique em 'Conectar ao Modem' primeiro.")
                return
        threading.Thread(target=task_func, daemon=True).start()

    def _cancel_sms_prompt_if_active(self):
        if self.client and self.client.awaiting_sms_body:
            def worker():
                self.ui_queue.put(("TX", "<ESC> (Cancelar SMS)"))
                resp = self.client.send_raw_bytes(b"\x1b")
                self.ui_queue.put(("RX", resp))
                self.ui_queue.put(("PROMPT_MODE", False))
            self._run_in_background(worker)

    def _send_raw_order(self):
        cmd = self.raw_cmd_var.get().strip()
        if not cmd:
            return

        # Se o modem estiver a aguardar o corpo de um SMS (após AT+CMGS="...")
        if self.client and self.client.awaiting_sms_body:
            self.raw_cmd_var.set("")
            def worker():
                if cmd.upper() == "ESC":
                    self.ui_queue.put(("TX", "<ESC> (Cancelar Envio SMS)"))
                    resp = self.client.send_raw_bytes(b"\x1b")
                else:
                    self.ui_queue.put(("TX", f"Corpo SMS: {cmd} <Ctrl+Z>"))
                    resp = self.client.send_raw_bytes(cmd.encode("utf-8") + b"\x1a")
                self.ui_queue.put(("PROMPT_MODE", False))
                self.ui_queue.put(("RX", resp))
            self._run_in_background(worker)
            return

        self._dispatch_cmd(cmd)

    def _dispatch_cmd(self, cmd: str):
        def worker():
            self.ui_queue.put(("TX", cmd))
            resp = self.client.send_command(cmd)
            if resp.status == "PROMPT":
                self.ui_queue.put(("PROMPT_MODE", True))
            self.ui_queue.put(("RX", resp))
        self._run_in_background(worker)

    def _order_full_init(self):
        def worker():
            self.ui_queue.put(("INFO", "A executar sequencia completa de inicializacao (ATE0 -> CMEE=1 -> PIN -> CREG -> CMGF=1 -> CNMI)..."))
            ok = self.client.initialize(pin=self.pin_var.get().strip(), wait_network_s=5.0)
            if ok:
                self.ui_queue.put(("INFO", "Inicializacao completa com sucesso! Modem registado na rede (+CREG: 0,1) e pronto para SMS/USSD."))
            else:
                self.ui_queue.put(("RX_ERR", "Aviso: A inicializacao foi concluida mas o registo de rede requer atencao."))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _order_unlock_pin(self):
        pin = self.pin_var.get().strip()
        self._dispatch_cmd(f'AT+CPIN="{pin}"')

    def _order_ussd(self):
        code = self.ussd_code_var.get().strip()
        def worker():
            self.ui_queue.put(("TX", f'AT+CUSD=1,"{code}"'))
            res = self.client.check_balance_ussd(code)
            if res["success"]:
                self.ui_queue.put(("INFO", f"Resposta USSD recebida: {res['text']}"))
            else:
                self.ui_queue.put(("RX_ERR", f"Falha no pedido USSD: {res['error']}"))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _order_send_sms(self):
        dest = self.sms_dest_var.get().strip()
        text = self.sms_text_box.get("1.0", tk.END).strip()
        retries = self.retry_count_var.get()
        if not dest or not text:
            messagebox.showwarning("Aviso", "Preencha o destinatario e o texto da mensagem.")
            return

        def worker():
            self.ui_queue.put(("INFO", f"A emitir ordem de envio de SMS para {dest} (Max retries: {retries})..."))
            res = self.client.send_sms(dest, text, max_retries=retries)
            if res["success"]:
                self.ui_queue.put(("INFO", f"SMS enviado com sucesso! Message Reference: {res.get('mr')} (Tentativas: {res.get('attempts')})"))
            else:
                self.ui_queue.put(("RX_ERR", f"Falha no envio de SMS apos {res.get('attempts')} tentativas: {res.get('error')}"))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _order_list_sms(self):
        def worker():
            self.ui_queue.put(("INFO", "A carregar mensagens do SIM (AT+CMGL)..."))
            msgs = self.client.list_sms("ALL")
            self.ui_queue.put(("INBOX_REFRESH", msgs))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _order_read_selected_sms(self):
        selected = self.inbox_tree.selection()
        if not selected:
            messagebox.showinfo("Informacao", "Selecione uma mensagem na tabela para ler.")
            return
        item = self.inbox_tree.item(selected[0])
        idx = int(item["values"][0])
        self._dispatch_cmd(f"AT+CMGR={idx}")

    def _order_delete_selected_sms(self):
        selected = self.inbox_tree.selection()
        if not selected:
            messagebox.showinfo("Informacao", "Selecione uma mensagem na tabela para apagar.")
            return
        item = self.inbox_tree.item(selected[0])
        idx = int(item["values"][0])
        def worker():
            self.ui_queue.put(("TX", f"AT+CMGD={idx}"))
            resp = self.client.send_command(f"AT+CMGD={idx}")
            self.ui_queue.put(("RX", resp))
            if resp.is_ok:
                self._order_list_sms()
        self._run_in_background(worker)

    def _order_inject_sms(self):
        sender = self.inject_sender_var.get().strip()
        text = self.inject_text_var.get().strip()
        if not sender or not text:
            return
        self._dispatch_cmd(f'AT#INJECT_SMS="{sender}","{text}"')

    def _order_set_profile(self):
        prof = self.profile_var.get().strip()
        self._dispatch_cmd(f'AT#PROFILE="{prof}"')

    def _order_set_fault(self):
        rate = self.fault_rate_var.get()
        self._dispatch_cmd(f"AT#FAULT_RATE={rate:.2f}")

    def _order_toggle_cds(self):
        val = 1 if self.cds_var.get() else 0
        self._dispatch_cmd(f"AT#DELIVERY_REPORT={val}")

    def _order_reset_modem(self):
        self._dispatch_cmd("AT#RESET")

    # -------------------------------------------------------------
    # Controlo das Aplicações de Alto Nível (Semana 6)
    # -------------------------------------------------------------

    def _toggle_voting_center(self):
        if not self.is_connected or not self.client:
            messagebox.showwarning("Aviso", "Conecte-se ao modem primeiro.")
            return

        if self.voting_center and self.voting_center.is_active:
            self.voting_center.stop()
            self.btn_toggle_voting.configure(text="Iniciar Centro de Votacao")
            self._log_info("Centro de Votacao encerrado.")
            self._update_apps_display()
        else:
            opcoes = {"1": "MQTT", "2": "CoAP", "3": "LoRaWAN", "4": "NB-IoT"}
            self.voting_center = VotingCenter(self.client, "Melhor protocolo IoT?", opcoes)
            self.voting_center.start()
            self.btn_toggle_voting.configure(text="Parar Centro de Votacao")
            self._log_info("Centro de Votacao SMS iniciado! Envie ou injete SMS com '1', '2', '3' ou '4'.")
            self._update_apps_display()

    def _simulate_vote(self, option_str: str):
        if not self.voting_center or not self.voting_center.is_active:
            self._toggle_voting_center()
        rand_num = f"+35191{int(time.time() * 10) % 10000000:07d}"
        def worker():
            self.ui_queue.put(("INFO", f"A injetar voto simulado de {rand_num} na opcao '{option_str}'..."))
            self.client.inject_sms(rand_num, option_str)
            time.sleep(0.8)
            self.ui_queue.put(("APPS_REFRESH", None))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _toggle_email_gateway(self):
        if not self.is_connected or not self.client:
            messagebox.showwarning("Aviso", "Conecte-se ao modem primeiro.")
            return

        if self.email_gateway and self.email_gateway.is_active:
            self.email_gateway.stop()
            self.btn_toggle_gateway.configure(text="Iniciar Gateway Email<->SMS")
            self._log_info("Gateway Email <-> SMS encerrado.")
            self._update_apps_display()
        else:
            self.email_gateway = EmailSMSGateway(self.client)
            self.email_gateway.start()
            self.btn_toggle_gateway.configure(text="Parar Gateway Email<->SMS")
            self._log_info("Gateway Email <-> SMS iniciado!")
            self._update_apps_display()

    def _simulate_sms_to_email(self):
        if not self.email_gateway or not self.email_gateway.is_active:
            self._toggle_email_gateway()
        def worker():
            payload = "EMAIL:docente@utad.pt | Relatorio TP1 | O sistema RSCM esta operacional."
            self.ui_queue.put(("INFO", f"A injetar SMS para Gateway: '{payload}'"))
            self.client.inject_sms("+351931112233", payload)
            time.sleep(0.8)
            self.ui_queue.put(("APPS_REFRESH", None))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _simulate_email_to_sms(self):
        if not self.email_gateway or not self.email_gateway.is_active:
            self._toggle_email_gateway()
        def worker():
            self.ui_queue.put(("INFO", "A encaminhar Email -> SMS pelo Gateway..."))
            self.email_gateway.relay_email_to_sms("secretaria@utad.pt", "+351912345678", "Nota Final", "O seu TP1 foi validado com sucesso.")
            self.ui_queue.put(("APPS_REFRESH", None))
            self.ui_queue.put(("REFRESH_TEL", None))
        self._run_in_background(worker)

    def _update_apps_display(self):
        if self.voting_center:
            res = self.voting_center.get_results()
            lines = [
                f"Estado: {'ATIVO' if self.voting_center.is_active else 'PARADO'}",
                f"Pergunta: {res['question']} (Total votos: {res['total_votes']})",
                "-" * 48
            ]
            for k, d in res["results"].items():
                lines.append(f" [{k}] {d['name']:<10}: {d['votes']} votos ({d['percentage']:.1f}%)")
            lines.append(f"Vencedor Atual: {res['winner']}")
            self.voting_status_box.delete("1.0", tk.END)
            self.voting_status_box.insert(tk.END, "\n".join(lines))

        if self.email_gateway:
            st = self.email_gateway.stats
            lines = [
                f"Estado: {'ATIVO' if self.email_gateway.is_active else 'PARADO'}",
                f"SMS Recebidos      : {st['sms_received']}",
                f"SMS -> Email (OK)  : {st['sms_to_email_success']} (Erros: {st['sms_to_email_errors']})",
                f"Email -> SMS (OK)  : {st['email_to_sms_sent']} (Falhas: {st['email_to_sms_failed']})",
                f"Emails na Outbox   : {len(self.email_gateway.email_outbox)}"
            ]
            if self.email_gateway.email_outbox:
                last = self.email_gateway.email_outbox[-1]
                lines.append(f"Ultimo Email: -> {last['to_email']} [{last['subject']}]")
            self.gateway_status_box.delete("1.0", tk.END)
            self.gateway_status_box.insert(tk.END, "\n".join(lines))

    # -------------------------------------------------------------
    # Telemetria e Registo Estruturado (Semana 7)
    # -------------------------------------------------------------

    def _refresh_telemetry_view(self):
        logs = default_telemetry.load_logs()
        metrics = default_telemetry.compute_metrics(logs)

        self.lbl_tel_metrics.configure(
            text=(
                f"Comandos AT: {metrics['total_commands']}  |  "
                f"SMS Enviados: {metrics['sms_sent']}  |  "
                f"SMS Recebidos: {metrics['sms_received']}  |  "
                f"Taxa de Erros: {metrics['error_rate_pct']:.1f}%  |  "
                f"Latencia Media: {metrics['avg_latency_ms']:.1f} ms"
            )
        )

        for item in self.tel_tree.get_children():
            self.tel_tree.delete(item)

        # Mostrar últimos 100 eventos
        for r in logs[-100:]:
            self.tel_tree.insert(
                "",
                tk.END,
                values=(
                    r.get("timestamp", ""),
                    r.get("port", ""),
                    r.get("at_command", ""),
                    r.get("response", ""),
                    r.get("internal_state", ""),
                    f"{float(r.get('latency_ms', 0.0)):.1f}"
                )
            )
        children = self.tel_tree.get_children()
        if children:
            self.tel_tree.see(children[-1])

        sum_lines = [
            f"{'COMANDO AT':<18} | {'QTD':>4} | {'ERROS':>5} | {'MEDIA (ms)':>10}",
            "-" * 46
        ]
        for cmd, info in metrics["per_command"].items():
            sum_lines.append(
                f"{cmd:<18} | {info['count']:>4} | {info['errors']:>5} | {info['avg_ms']:>9.1f}ms"
            )
        self.tel_summary_box.delete("1.0", tk.END)
        self.tel_summary_box.insert(tk.END, "\n".join(sum_lines))

    def _export_telemetry_report(self):
        report = default_telemetry.generate_summary_report(save_to_file=True)
        self._refresh_telemetry_view()
        self._log_info(f"Sumario de Telemetria exportado para: {default_telemetry.summary_path}")
        messagebox.showinfo(
            "Sumario de Telemetria Gerado",
            f"O relatorio automatico de metricas foi guardado em:\n{default_telemetry.summary_path}\n\n"
            f"CSV: {default_telemetry.csv_path}\nJSON: {default_telemetry.json_path}"
        )

    def _clear_telemetry_logs(self):
        default_telemetry.clear_logs()
        self._refresh_telemetry_view()
        self._log_info("Registos de telemetria (CSV/JSON) reiniciados.")

    # -------------------------------------------------------------
    # Processamento de Eventos da Consola e UI
    # -------------------------------------------------------------

    def _process_ui_queue(self):
        while not self.ui_queue.empty():
            try:
                ev = self.ui_queue.get_nowait()
                ev_type = ev[0]

                if ev_type == "TX":
                    cmd = ev[1]
                    self._append_console(f"[TX] Ordem: {cmd}\n", "TX")

                elif ev_type == "PROMPT_MODE":
                    active = ev[1]
                    if active:
                        self.lbl_manual_prompt.configure(text="Texto do SMS (Enter=Enviar, ESC=Cancelar):", foreground="#0284c7")
                        self.raw_cmd_var.set("")
                        self.raw_entry.focus_set()
                    else:
                        self.lbl_manual_prompt.configure(text="Ordem AT Manual:", foreground="#0f172a")

                elif ev_type == "RX":
                    resp: ATResponse = ev[1]
                    lat_str = f"({resp.latency_ms:.1f}ms)"
                    tag = "RX_OK" if resp.is_ok else "RX_ERR"
                    if resp.status == "PROMPT":
                        lines_text = "> (Modem aguarda o texto do SMS: escreva a mensagem na barra acima e prima Enter)"
                    else:
                        lines_text = "\n".join(resp.lines) if resp.lines else resp.status
                    self._append_console(f"[RX] {resp.status} {lat_str}:\n{lines_text}\n", tag)
                    self._refresh_telemetry_view()

                elif ev_type == "URC":
                    urc_t, data = ev[1], ev[2]
                    if urc_t == "CMTI":
                        self._append_console(
                            f"[URC ASSINCRONO] +CMTI: Nova mensagem recebida no slot {data.get('index')} (Memoria: {data.get('storage')})\n",
                            "URC"
                        )
                        self.root.after(300, self._order_list_sms)
                        self.root.after(600, self._update_apps_display)
                    elif urc_t == "CDS":
                        self._append_console(f"[URC ASSINCRONO] {data.get('raw')}\n", "URC")
                    self._refresh_telemetry_view()

                elif ev_type == "INFO":
                    self._append_console(f"[INFO] {ev[1]}\n", "INFO")

                elif ev_type == "RX_ERR":
                    self._append_console(f"[ERRO] {ev[1]}\n", "RX_ERR")

                elif ev_type == "INBOX_REFRESH":
                    msgs = ev[1]
                    for item in self.inbox_tree.get_children():
                        self.inbox_tree.delete(item)
                    for m in msgs:
                        self.inbox_tree.insert("", tk.END, values=(m["index"], m["status"], m["sender"], m["timestamp"], m["text"]))
                    self._append_console(f"[INFO] Caixa de entrada atualizada ({len(msgs)} mensagens encontradas).\n", "INFO")

                elif ev_type == "APPS_REFRESH":
                    self._update_apps_display()

                elif ev_type == "REFRESH_TEL":
                    self._refresh_telemetry_view()

            except Exception as e:
                print(f"Erro no processamento da UI queue: {e}")

        self.root.after(100, self._process_ui_queue)

    def _append_console(self, text: str, tag: str):
        t_stamp = time.strftime("[%H:%M:%S] ")
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, t_stamp, "INFO")
        self.console.insert(tk.END, text, tag)
        self.console.see(tk.END)
        self.console.configure(state=tk.DISABLED)

    def _log_info(self, text: str):
        self.ui_queue.put(("INFO", text))

    def _log_error(self, text: str):
        self.ui_queue.put(("RX_ERR", text))

    def _clear_console(self):
        self.console.configure(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    app = DesktopOrderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
