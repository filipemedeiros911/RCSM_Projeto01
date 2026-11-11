# Sumário Automático de Telemetria e Registo (Semana 7 - Checkpoint TP1)
**Data de Geração:** 2026-11-05 15:15:10  
**Ficheiro CSV:** `C:\Users\X1605\Desktop\Projeto Redes #1\logs\telemetria_at.csv`  
**Ficheiro JSON:** `C:\Users\X1605\Desktop\Projeto Redes #1\logs\telemetria_at.json`

## 1. Métricas Globais de Síntese
- **Total de Eventos Registados:** 231
- **Total de Comandos AT Executados:** 217 (Sucesso: 182 | Erros: 35)
- **Taxa Global de Erros:** 16.13%
- **Nº de SMS Enviados (+CMGS):** 13
- **Nº de SMS Recebidos (+CMTI):** 13
- **Relatórios de Entrega (+CDS):** 1
- **Latência Global (Mín / Média / Máx):** 11.6 ms / 231.8 ms / 3885.1 ms

## 2. Latências e Taxa de Erros por Comando AT
| Comando AT | Execuções | Sucessos | Erros | Taxa Erro (%) | Lat. Mín (ms) | Lat. Média (ms) | Lat. Máx (ms) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `AT` | 1 | 1 | 0 | 0.0% | 44.2 | 44.2 | 44.2 |
| `AT#DELIVERY_REPORT` | 7 | 7 | 0 | 0.0% | 37.5 | 44.3 | 50.2 |
| `AT#FAULT_RATE` | 2 | 2 | 0 | 0.0% | 36.1 | 40.4 | 44.6 |
| `AT#INJECT_SMS` | 12 | 12 | 0 | 0.0% | 38.8 | 46.1 | 56.6 |
| `AT#PROFILE` | 4 | 4 | 0 | 0.0% | 40.1 | 44.7 | 49.5 |
| `AT+CMGD` | 13 | 13 | 0 | 0.0% | 47.2 | 67.6 | 93.0 |
| `AT+CMGF` | 1 | 1 | 0 | 0.0% | 31.0 | 31.0 | 31.0 |
| `AT+CMGL` | 83 | 83 | 0 | 0.0% | 50.6 | 101.8 | 149.1 |
| `AT+CMGR` | 14 | 12 | 2 | 14.3% | 53.1 | 78.1 | 115.0 |
| `AT+CMGS` | 65 | 33 | 32 | 49.2% | 204.1 | 503.7 | 799.7 |
| `AT+CNMI` | 1 | 1 | 0 | 0.0% | 23.8 | 23.8 | 23.8 |
| `AT+COPS?` | 1 | 1 | 0 | 0.0% | 239.0 | 239.0 | 239.0 |
| `AT+CPIN` | 1 | 1 | 0 | 0.0% | 142.3 | 142.3 | 142.3 |
| `AT+CPIN?` | 1 | 1 | 0 | 0.0% | 142.3 | 142.3 | 142.3 |
| `AT+CPMS?` | 1 | 1 | 0 | 0.0% | 38.7 | 38.7 | 38.7 |
| `AT+CREG?` | 2 | 2 | 0 | 0.0% | 135.7 | 162.0 | 188.3 |
| `AT+CSQ` | 4 | 4 | 0 | 0.0% | 11.6 | 13.2 | 15.9 |
| `AT+CUSD` | 2 | 1 | 1 | 50.0% | 1013.8 | 2449.5 | 3885.1 |
| `ATE0` | 1 | 1 | 0 | 0.0% | 19.1 | 19.1 | 19.1 |
| `ATI` | 1 | 1 | 0 | 0.0% | 59.9 | 59.9 | 59.9 |

## 3. Distribuição de Eventos por Estado Interno do Modem
| Estado Interno | Ocorrências |
|:---|:---:|
| `PIN_REQUIRED` | 4 |
| `REGISTRATION` | 1 |
| `SIM_READY` | 1 |
| `SMS_STACK_USSD` | 225 |
