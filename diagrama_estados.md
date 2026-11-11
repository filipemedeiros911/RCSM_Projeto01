# Diagrama de Estados do Emulador de Modem AT (Semanas 1–7)

**Disciplina:** Redes e Serviços de Comunicações Móveis (RSCM) — 2026/2027  
**Instituição:** Universidade de Trás-os-Montes e Alto Douro (UTAD)  
**Ficheiro de implementação:** [`at_emulator.py`](file:///c:/Users/X1605/Desktop/Projeto%20Redes%20%231/at_emulator.py) (`class ModemState(Enum)`)

O diagrama visual em formato vetorial encontra-se em [`diagrama_estados.svg`](./diagrama_estados.svg).

---

## 1. Diagrama da Máquina de Estados (`ModemState`)

```mermaid
stateDiagram-v2
    [*] --> BOOT: Inicializar ModemEmulator

    BOOT --> PIN_REQUIRED: Arranque automático concluído

    %% Estado PIN_REQUIRED
    PIN_REQUIRED --> PIN_REQUIRED: AT+CPIN? -> +CPIN: SIM PIN\nComandos de rede/SMS -> +CME ERROR: 10
    PIN_REQUIRED --> PIN_REQUIRED: AT+CPIN="<errado>" (tentativas > 0)\n-> -1 tentativa / +CME ERROR: 16
    PIN_REQUIRED --> SIM_PUK: 3.ª tentativa falhada (tentativas == 0)\n-> +CME ERROR: 12
    PIN_REQUIRED --> SIM_READY: AT+CPIN="1234"\n-> OK (inicia timer de rede)

    %% Estado SIM_PUK (Bloqueio PUK)
    SIM_PUK --> SIM_PUK: AT+CPIN? -> +CPIN: SIM PUK\nPUK inválido -> +CME ERROR: 12\nRede/SMS -> +CME ERROR: 10
    SIM_PUK --> SIM_READY: AT+CPIN="00000000","<novo_pin>"\n-> OK (repõe 3 tentativas e inicia timer)

    %% Estado SIM_READY
    SIM_READY --> SIM_READY: AT+CPIN? -> +CPIN: READY\nAT+CSQ -> RSSI do perfil
    SIM_READY --> REGISTRATION: t >= 0.35 s ou consulta\nAT+CREG? / AT+CGREG? / AT+COPS? / AT+CSQ
    SIM_READY --> SMS_STACK_USSD: comando recebido após t >= 4.0 s\n(NETWORK_SEARCH_DELAY)

    %% Estado REGISTRATION (Procura de célula)
    REGISTRATION --> REGISTRATION: t < 4.0 s\nAT+CREG? -> +CREG: 0,2 (searching)\nAT+COPS? -> +COPS: 0\nSMS/USSD -> +CME ERROR: 10
    REGISTRATION --> SMS_STACK_USSD: comando ou injeção após t >= 4.0 s\n(NETWORK_SEARCH_DELAY)

    %% Estado SMS_STACK_USSD (Registado e Operacional)
    SMS_STACK_USSD --> SMS_STACK_USSD: AT+CREG? -> +CREG: 0,1 (ou 0,0 em NOSERVICE)\nAT+COPS? -> "MEO 4G" / "MEO 3G" / "MEO 2G"\nStack SMS (+CMGS, +CMGL, +CMGR, +CMGD)\nUSSD (+CUSD) & Eventos Assíncronos (+CMTI, +CDS)\nExtensões: AT#PROFILE, AT#FAULT_RATE, AT#DELIVERY_REPORT

    %% Reset Global
    PIN_REQUIRED --> PIN_REQUIRED: AT#RESET
    SIM_PUK --> PIN_REQUIRED: AT#RESET
    SIM_READY --> PIN_REQUIRED: AT#RESET
    REGISTRATION --> PIN_REQUIRED: AT#RESET
    SMS_STACK_USSD --> PIN_REQUIRED: AT#RESET

    state "0: BOOT" as BOOT
    state "1: PIN_REQUIRED" as PIN_REQUIRED
    state "2: SIM_PUK" as SIM_PUK
    state "3: SIM_READY" as SIM_READY
    state "4: REGISTRATION" as REGISTRATION
    state "5: SMS_STACK_USSD" as SMS_STACK_USSD
```

---

## 2. Sub-máquina de Envio Interativo de SMS (`waiting_for_sms_body`)

Dentro do estado `SMS_STACK_USSD`, o comando `AT+CMGS="<destino>"` ativa um sub-estado interativo de leitura de bytes na sessão (`waiting_for_sms_body = True`):

```mermaid
stateDiagram-v2
    [*] --> MODO_COMANDO: Estado SMS_STACK_USSD

    MODO_COMANDO --> AGUARDAR_CORPO_SMS: AT+CMGS="<destino>"\n(devolve prompt "> ")
    AGUARDAR_CORPO_SMS --> AGUARDAR_CORPO_SMS: Carateres de texto\n(acumula em sms_body_buffer)
    AGUARDAR_CORPO_SMS --> MODO_COMANDO: CTRL+Z (0x1A) ou Enter com texto\n-> finalizar_envio_sms()\n-> +CMGS: <mr> + OK (ou +CMS ERROR: 500 se falha)\n-> Dispara thread +CDS (se ativo)
    AGUARDAR_CORPO_SMS --> MODO_COMANDO: ESC (0x1B)\n-> Cancela envio e limpa buffer\n-> OK
```

---

## 3. Tabela Resumo dos Estados e Comportamento

| Estado (`ModemState`) | Código | Resposta `AT+CPIN?` | Resposta `AT+CREG?` | Comandos de Rede (`+CSQ`, `+COPS?`) | Stack SMS e USSD (`+CMGS`, `+CMGR`, `+CUSD`) |
|:---|:---:|:---|:---|:---|:---|
| **`BOOT`** | `0` | — *(transita logo para `PIN_REQUIRED`)* | — | — | — |
| **`PIN_REQUIRED`** | `1` | `+CPIN: SIM PIN` | `+CME ERROR: 10` | `+CME ERROR: 10` | `+CME ERROR: 10` |
| **`SIM_PUK`** | `2` | `+CPIN: SIM PUK` | `+CME ERROR: 10` | `+CME ERROR: 10` | `+CME ERROR: 10` |
| **`SIM_READY`** | `3` | `+CPIN: READY` | `+CREG: 0,0` *(ou transita p/ `0,2`)* | Permitido (`+CSQ` devolve sinal; `+COPS: 0`) | `+CME ERROR: 10` |
| **`REGISTRATION`** | `4` | `+CPIN: READY` | `+CREG: 0,2` *(procura < 4 s)* | Permitido (`+CSQ` devolve sinal; `+COPS: 0`) | `+CME ERROR: 10` |
| **`SMS_STACK_USSD`** | `5` | `+CPIN: READY` | `+CREG: 0,1` *(ou `0,0` em `NOSERVICE`)* | Operador e RSSI conforme `AT#PROFILE` (`LTE`/`3G`/`2G`/`NOSERVICE`) | **Ativo** (Suporta SMS, USSD, `+CMTI`, `+CDS` e injeção de falhas) |

---

## 4. Notas Técnicas de Implementação

1. **Comandos Sempre Disponíveis (Independentes do Estado):**
   Os comandos básicos de configuração do terminal — `AT`, `ATE0`, `ATE1`, `ATI`, `AT+CMEE?/=`, `AT+CMGF?/=`, `AT+CSCA?/=`, `AT+CNMI?/=` e `AT#RESET` — são aceites em qualquer estado após o arranque.
2. **Temporização da Procura de Rede (`_atualizar_registo_rede`):**
   A transição `SIM_READY` $\rightarrow$ `REGISTRATION` $\rightarrow$ `SMS_STACK_USSD` é controlada pelo relógio interno (`self.network_search_start`) sem bloquear a thread principal. O método `_atualizar_registo_rede()` é invocado no início de `_executar_logica_comando()` e de `injetar_sms_recebido()`, garantindo que o modem passa para `REGISTRATION` após $0.35\text{ s}$ (ou na primeira consulta de rede) e para `SMS_STACK_USSD` assim que decorrem os $4.0\text{ s}$ definidos em `NETWORK_SEARCH_DELAY`.
3. **Efeito das Extensões (Semana 6) no Estado `SMS_STACK_USSD`:**
   - Se `network_profile == "NOSERVICE"`, o modem mantém-se no estado `SMS_STACK_USSD`, mas simula perda de cobertura: `AT+CREG?` responde `+CREG: 0,0`, `AT+CSQ` responde `99,99`, `AT+CMGS` falha com `+CMS ERROR: 330` e `AT+CUSD` falha com `+CME ERROR: 515`.
   - Se `fault_rate > 0.0`, o comando `AT+CMGS` pode falhar probabilisticamente com `+CMS ERROR: 500`, acionando a *Retry Policy* do `ModemClient`.
