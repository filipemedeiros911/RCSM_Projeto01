# Manual de Utilização do Projeto (Semana 6)
**Disciplina:** Redes Sem Fios e Comunicações Móveis (RSCM) — 2026/2027  
**Instituição:** Universidade de Trás-os-Montes e Alto Douro (UTAD)  
**Trabalho Prático 1:** Emulação de Modems AT, Interface Desktop de Ordens e Aplicações Móveis

---

## 1. Visão Geral da Arquitetura

O ecossistema foi construído de forma modular segundo o protocolo oficial de RSCM:
```
 +---------------------------------------------------------+
 |             INTERFACE DESKTOP (desktop_app.py)          |
 |    (Onde o utilizador emite as ordens e comandos)       |
 +---------------------------------------------------------+
                             |
                   [Porta A: COM5 ou TCP]
                             |
           +-------------------------------------+
           |         SETUP (com0com / Ponte)      |
           |     Par Virtual Pareado COM5 <-> COM6|
           +-------------------------------------+
                             |
                   [Porta B: COM6 ou TCP]
                             |
 +---------------------------------------------------------+
 |               EMULADOR AT (at_emulator.py)              |
 |  - Simula latência física real (tabela configurável)    |
 |  - Máquina de estados: BOOT -> PIN -> REDE -> SMS/USSD  |
 |  - Extensões Semana 6: Perfis, Falhas, Relatórios CDS   |
 +---------------------------------------------------------+
```

---

## 2. Estrutura dos Ficheiros

| Ficheiro | Descrição |
|:---|:---|
| **`desktop_app.py`** | **Interface Gráfica Desktop (Tkinter)**. Ponto de comando onde o utilizador dá as ordens. Conecta-se à Porta A (COM5) ou TCP e monitoriza em tempo real `[TX]` ordens, `[RX]` respostas (com latência em ms) e `[URC]` eventos assíncronos. |
| **`at_emulator.py`** | **Emulador do Modem AT**. Executa "atrás" da Porta B (COM6) ou TCP 5555. Implementa a máquina de estados, tabela de latências realistas, SMS, USSD e extensões da Semana 6. |
| **`modem_client.py`** | **Driver Cliente Python**. Gere a comunicação série/socket, sincronização de comandos, thread de escuta assíncrona (+CMTI/+CDS) e *Retry Policy* com recuperação automática de falhas. |
| **`voting_center.py`** | **Aplicação de Alto Nível 1 (Centro de Votação SMS)**. Sondagens interativas, validação de 1 voto por número (rejeição de duplicados), envio de SMS de confirmação (recibo) e apuramento em tempo real. |
| **`email_sms_gateway.py`** | **Aplicação de Alto Nível 2 (Gateway Email ↔ SMS)**. Conversão bidirecional entre mensagens SMS e emails, verificação sintática e envio de confirmações. |
| **`plano_testes.md`** | **Documentação do Plano de Testes**. Matriz formal de 36 casos de teste (TC-01 a TC-36) com entradas, saídas esperadas e tempos de latência. |
| **`test_plan_runner.py`** | **Executor Automatizado de Testes**. Executa deterministamente os 36 casos de teste contra o emulador e gera o relatório final com taxa de sucesso. |
| **`COMO_USAR.md`** | **Este manual de instruções atualizado**. |

---

## 3. Configuração do Setup (com0com) no Windows

Para ligar a interface ao emulador através de portas série virtuais:

1. Abra o atalho de **Setup** do com0com no seu Ambiente de Trabalho (`Setup.lnk`) ou através do menu iniciar:
   ```
   C:\Program Files (x86)\com0com\setupg.exe
   ```
2. No Setup do com0com, configure um par de portas virtuais pareadas:
   - **Port Name 1:** `COM5` (Porta da Interface de Ordens)
   - **Port Name 2:** `COM6` (Porta do Emulador AT)
   - Ative as opções *"enable buffer overrun"* caso disponível e clique em **Apply**.

> [!TIP]
> **Modo Socket TCP Imediato (Sem Instalar Drivers):**  
> Se não tiver o com0com instalado ou não quiser configurar portas COM virtuais, todo o sistema suporta **TCP de forma nativa e transparente** na porta `5555` (`127.0.0.1:5555`). Funciona exatamente igual!

---

## 4. Como Executar e Utilizar a Interface Desktop

### Passo 1: Iniciar o Emulador AT (Porta B)
Num terminal PowerShell, inicie o emulador na porta desejada:

- **Se usar o com0com (Porta COM6):**
  ```powershell
  python at_emulator.py --serial COM6
  ```
- **Se usar TCP (127.0.0.1:5555):**
  ```powershell
  python at_emulator.py --tcp 5555
  ```
*(O emulador inicia no estado de `BOOT` aguardando ordens).*

---

### Passo 2: Iniciar a Interface Desktop (Porta A)
Num segundo terminal (ou dando duplo clique no ficheiro):
```powershell
python desktop_app.py
```

### Passo 3: Dar Ordens na Interface
1. **Conectar:**
   - Se estiver a usar o com0com, certifique-se de que está preenchido `COM5` (baud: `9600`) e clique em **"Conectar ao Modem"**.
   - Se estiver a usar TCP, clique no botão rápido **"Usar TCP (127.0.0.1:5555)"** e clique em **"Conectar ao Modem"**.
   - O indicador de estado passa a verde: `[CONECTADO]`.

2. **Ordem de Inicialização (Setup):**
   - No separador *"Ordens de Setup & Rede"*, clique em **"Dar Ordem: Inicializacao Completa (Auto)"**.
   - O emulador recebe as ordens sequenciais (`ATE0`, `AT+CMEE=1`, `AT+CPIN="1234"`, aguarda registo de rede `+CREG: 0,1`, configura `AT+CMGF=1` e `AT+CNMI=2,1,0,0,0`).
   - Veja na consola inferior as respostas com a indicação da latência física medida em milissegundos.

3. **Ordem de Envio de SMS (com Retry Policy):**
   - Abra o separador *"Ordens de Envio de SMS"*.
   - Preencha o número de destino e o texto.
   - Configure o número de tentativas em caso de erro (Retry Policy: 1 a 5).
   - Clique em **"DAR ORDEM DE ENVIO DE SMS"**.

4. **Ordem de Consulta de Saldo USSD:**
   - No separador *"Ordens de Setup & Rede"*, insira o código `*#123#` e clique em **"Dar Ordem: Consultar Saldo USSD"**.
   - O emulador simula a latência de rede (500 a 3000 ms) e devolve o saldo do cartão.

5. **Extensões da Semana 6:**
   - **Perfis de Rede Dinâmicos:** No separador *"Extensoes Semana 6"*, selecione um perfil (`LTE`, `3G`, `2G` ou `NOSERVICE`) e clique em **"Dar Ordem: Aplicar Perfil"**. Ao consultar `AT+COPS?` ou `AT+CSQ`, os valores mudam dinamicamente!
   - **Falhas Intermitentes:** Ajuste a barra deslizante da taxa de falha (ex: 40%) e tente enviar SMS para ver a *Retry Policy* a retransmitir e recuperar automaticamente em caso de erro!
   - **Relatórios de Entrega (+CDS):** Marque a opção de relatórios de entrega. Ao enviar um SMS, verá surgir na consola a notificação assíncrona `[URC ASSINCRONO] +CDS:...`.

6. **Injeção de Mensagens na Rede (Simulação):**
   - No separador *"Caixa de Entrada & Simulacao"*, defina um remetente simulado e um texto (ex: `Voto na opcao 1`), e clique em **"Injetar Mensagem na Rede"**.
   - Imediatamente o modem emite o evento assíncrono `+CMTI` e a tabela de mensagens da interface atualiza-se!

7. **Ordens AT Manuais:**
   - Na barra inferior, pode escrever qualquer comando AT padrão (ex: `AT+CSQ`, `ATI`, `AT+COPS=?`) e clicar em **"Executar Ordem"** ou pressionar Enter.

---

## 5. Como Executar as Aplicações de Alto Nível

### A. Centro de Votação SMS (`voting_center.py`)
Inicia um centro de recolha e apuramento de votos por SMS:
```powershell
python voting_center.py
```
- O centro monitoriza a chegada de SMS.
- Ao receber uma opção (ex: "1" ou "2"), regista o voto e envia automaticamente um SMS de recibo de confirmação ao votante.
- Se o mesmo número tentar votar uma segunda vez, o voto é rejeitado e é enviado um SMS de aviso.
- O SMS processado é automaticamente limpo da memória do SIM (`AT+CMGD`).

### B. Gateway Email ↔ SMS (`email_sms_gateway.py`)
Inicia o gateway bidirecional:
```powershell
python email_sms_gateway.py
```
- **Fluxo SMS ➔ Email:** Envie um SMS com o formato:
  `EMAIL:destino@dominio.pt | Assunto | Texto da mensagem`
  O gateway faz a conversão sintática, coloca o email na fila de saída e envia um SMS de confirmação ao telemóvel.
- **Fluxo Email ➔ SMS:** Encaminha mensagens de email para a rede móvel formatadas como SMS.

---

## 6. Como Executar o Plano de Testes Automatizado

Para validar deterministicamente os **36 casos de teste** (TC-01 a TC-36) sem necessitar de intervenção manual:
```powershell
python test_plan_runner.py
```
O runner:
1. Inicia um emulador local em ambiente controlado.
2. Executa toda a bateria de testes (Comandos Básicos, PIN, Registo, SMS, USSD, Perfis 3G/2G/NOSERVICE, Falhas Intermitentes com Retry Policy, CDS e Aplicações).
3. Exibe uma tabela detalhada com os tempos de latência e o resultado de cada teste (`[PASS]` / `[FAIL]`).
4. Apresenta a percentagem final de sucesso (100%).
