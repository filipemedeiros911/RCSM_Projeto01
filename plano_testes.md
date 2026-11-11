# Plano de Testes Determinístico (Semana 6)
**Disciplina:** Redes Sem Fios e Comunicações Móveis (RSCM) — 2026/2027  
**Instituição:** Universidade de Trás-os-Montes e Alto Douro (UTAD)  
**Trabalho Prático 1:** Simulação e Emulação de Modems AT

---

## 1. Visão Geral e Objetivos do Plano de Testes

O presente plano de testes determinístico tem como objetivo validar exaustivamente a conformidade do emulador AT (`at_emulator.py`), do driver cliente (`modem_client.py`), das extensões de rede e das aplicações de alto nível (Centro de Votação e Gateway Email-SMS).

### Critérios de Cobertura:
1. **Casos de Sucesso (Happy Path):** Sequências nominais de arranque, autenticação por PIN, registo de rede, envio/receção de SMS e comandos USSD.
2. **Casos de Erro e Exceção:** PIN incorreto com decremento de tentativas, comandos antes de desbloqueio (`+CME ERROR: 10`), códigos USSD desconhecidos e parâmetros inválidos.
3. **Casos de Borda (Edge Cases):** Esgotamento de tentativas de PIN, leitura de slots de mensagens apagadas ou inexistentes (`+CMS ERROR: 321`), cancelamento de envio de SMS via ESC (`\x1b`).
4. **Extensões da Semana 6:** Perfis de rede dinâmicos (`AT#PROFILE`), taxas de falha intermitente (`AT#FAULT_RATE`) com *Retry Policy*, e relatórios assíncronos de entrega (`+CDS`).
5. **Aplicações de Alto Nível:** Regras de negócio de votação (unicidade de voto por número e recibo) e encaminhamento bidirecional de emails por SMS.

---

## 2. Matriz de Casos de Teste (TC-01 a TC-36)

| ID | Categoria | Entrada / Comando AT | Saída Esperada | Latência Típica | Notas e Critério de Sucesso |
|:---|:---|:---|:---|:---:|:---|
| **TC-01** | Básicos | `AT` | `OK` | 30–50 ms | Modem responde e confirma sincronismo de linha. |
| **TC-02** | Básicos | `ATE0` | `OK` | 30–50 ms | Desativação do eco de caracteres. |
| **TC-03** | Básicos | `ATE1` | `OK` | 30–50 ms | Reativação do eco de caracteres. |
| **TC-04** | Básicos | `ATI` | Identificação do modem + `OK` | 50–100 ms | Devolve fabricante (UTAD), modelo e revisão. |
| **TC-05** | PIN / Estado | `AT+CPIN?` (em BOOT) | `+CPIN: SIM PIN` + `OK` | 30–50 ms | Verifica que o modem exige PIN no arranque. |
| **TC-06** | Erro / Estado | `AT+CMGL="ALL"` (pré-PIN) | `+CME ERROR: 10` | 30–50 ms | Acesso a SMS é rejeitado antes de desbloquear PIN. |
| **TC-07** | Erro / PIN | `AT+CPIN="9999"` | `+CME ERROR: 16` | 80–150 ms | PIN incorreto: decrementa tentativas (3 -> 2). |
| **TC-08** | Sucesso / PIN | `AT+CPIN="1234"` | `OK` | 80–150 ms | PIN correto: transição para estado `REGISTRATION`. |
| **TC-09** | Sucesso / PIN | `AT+CPIN?` (pós-PIN) | `+CPIN: READY` + `OK` | 30–50 ms | Confirmação de SIM pronto. |
| **TC-10** | Rede / Registo | `AT+CREG?` (t < 4.0s) | `+CREG: 0,2` + `OK` | 30–50 ms | Modem em busca de rede móvel (`searching`). |
| **TC-11** | Rede / Registo | `AT+CREG?` (t >= 4.0s) | `+CREG: 0,1` + `OK` | 30–50 ms | Registado na rede de origem (`registered, home`). |
| **TC-12** | Rede / Sinal | `AT+CSQ` | `+CSQ: 18,99` + `OK` | 40–90 ms | Nível de sinal medido (RSSI 18 = -77 dBm). |
| **TC-13** | Rede / Operador | `AT+COPS?` | `+COPS: 0,0,"MEO",7` + `OK` | 50–120 ms | Nome do operador e tecnologia de acesso LTE. |
| **TC-14** | Rede / Operador | `AT+COPS=?` | Lista de operadores + `OK` | 100–300 ms | Varrimento de operadores móveis circundantes. |
| **TC-15** | SMS / Config | `AT+CMGF=1` | `OK` | 30–50 ms | Configuração do modo texto para SMS. |
| **TC-16** | SMS / Config | `AT+CSCA?` | `+CSCA: "+351910000000",145` | 30–50 ms | Consulta do endereço do SMSC do operador. |
| **TC-17** | SMS / Config | `AT+CNMI=2,1,0,0,0` | `OK` | 30–50 ms | Configuração das notificações assíncronas +CMTI. |
| **TC-18** | SMS / Envio | `AT+CMGS="+351912345678"` | Prompt `>` -> corpo -> `\x1a` -> `+CMGS: <mr>` + `OK` | 200–800 ms | Envio nominal de SMS com atribuição de MR. |
| **TC-19** | SMS / Listagem | `AT+CMGL="ALL"` | Lista de SMS armazenados + `OK` | 50–150 ms | Lista mensagens com metadados e estado. |
| **TC-20** | SMS / Leitura | `AT+CMGR=1` | `+CMGR: "REC READ",...` + Texto | 50–120 ms | Leitura de mensagem e transição UNREAD->READ. |
| **TC-21** | SMS / Limpeza | `AT+CMGD=1` | `OK` | 40–100 ms | Mensagem apagada com sucesso da memória. |
| **TC-22** | Edge / SMS | `AT+CMGR=999` | `+CMS ERROR: 321` | 40–80 ms | Tentativa de ler índice inexistente/apagado. |
| **TC-23** | USSD / Sucesso | `AT+CUSD=1,"*#123#"` | `+CUSD: 0,"Saldo: 14.50 EUR",15` | 500–3000 ms | Consulta nominal de saldo pré-pago via USSD. |
| **TC-24** | USSD / Sucesso | `AT+CUSD=1,"*100#"` | `+CUSD: 0,"Saldo: 14.50 EUR",15` | 500–3000 ms | Código alternativo suportado. |
| **TC-25** | USSD / Gestão | `AT+CUSD=2` | `OK` | 100–300 ms | Cancelamento da sessão USSD pelo utilizador. |
| **TC-26** | USSD / Erro | `AT+CUSD=1,"*#999#"` | `+CUSD: 2` ou `ERROR` | 500–3000 ms | Código inválido ou timeout da rede simulado. |
| **TC-27** | Extensão Perfil | `AT#PROFILE?` | `#PROFILE: "LTE"` + `OK` | 20–40 ms | Consulta do perfil de rede ativo por omissão. |
| **TC-28** | Extensão Perfil | `AT#PROFILE="3G"` | `OK` (altera `+COPS?` p/ "3G", `+CSQ` p/ 14) | 30–60 ms | Comutação dinâmica de perfil para 3G. |
| **TC-29** | Extensão Perfil | `AT#PROFILE="2G"` | `OK` (altera `+COPS?` p/ "GSM", `+CSQ` p/ 9) | 30–60 ms | Comutação dinâmica de perfil para 2G (GPRS). |
| **TC-30** | Extensão Perfil | `AT#PROFILE="NOSERVICE"` | `OK` (altera `+CREG?` p/ 0,0 e `+CSQ` p/ 99) | 30–60 ms | Simulação de perda total de cobertura de rede. |
| **TC-31** | Extensão Falha | `AT#FAULT_RATE=0.0` | `OK` | 20–40 ms | Taxa zero: funcionamento 100% determinístico. |
| **TC-32** | Extensão Falha | `AT#FAULT_RATE=0.5` | Injeção de erro temporário | Variável | Cliente aciona Retry Policy e reenvia com sucesso. |
| **TC-33** | Extensão Falha | `AT#FAULT_RATE=1.0` | `+CMS ERROR: 500` persistente | Variável | Esgotamento do limite de retries reportado com segurança. |
| **TC-34** | Extensão CDS | `AT#DELIVERY_REPORT=1` | URC assíncrono `+CDS:` | ~1000 ms | Modem emite confirmação de entrega assíncrona. |
| **TC-35** | App Votação | Votação SMS (`voting_center.py`) | Voto aceite + Recibo SMS | Integrado | Validação de regra 1 voto/número e rejeição de duplicado. |
| **TC-36** | App Gateway | Gateway (`email_sms_gateway.py`) | Conversão SMS -> Email + Confirmação | Integrado | Parsing sintático de email e encaminhamento bidirecional. |
| **TC-37** | Capacidades | `AT+CMGF=?` / `AT+CNMI=?` | `+CMGF: (0,1)` e faixas `+CNMI` | 30–80 ms | Validação das capacidades suportadas pelo modem (Secção 3.3). |
| **TC-38** | Memória SIM | `AT+CPMS?` | `+CPMS: "SM",<usados>,50,...` + `OK` | 30–60 ms | Consulta de ocupação e capacidade de armazenamento SMS. |
| **TC-39** | Edge / PUK | 3x `AT+CPIN="0000"` | `+CME ERROR: 12` e `+CPIN: SIM PUK` | 80–150 ms | Bloqueio do cartão SIM em PUK após esgotar 3 tentativas. |
| **TC-40** | Telemetria S7 | `generate_summary_report()` | `telemetria_at.csv`/`.json` + `sumario_telemetria.md` | < 50 ms | Registo estruturado e sumário automático de métricas (Semana 7). |

---

## 3. Execução Automatizada dos Testes

O ficheiro de execução de testes [`test_plan_runner.py`](file:///c:/Users/X1605/Desktop/Projeto%20Redes%20#1/test_plan_runner.py) implementa a validação automatizada de todos os casos de teste acima descritos.

Para executar toda a bateria de testes e gerar o relatório determinístico:
```powershell
python test_plan_runner.py
```
O runner inicializa uma instância do emulador, executa as asserções de forma cronometrada e apresenta a taxa de aprovação com código de saída 0.
