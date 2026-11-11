"""
Módulo de Registo Estruturado (Logging) e Telemetria (Semana 7)
Disciplina: Redes e Serviços de Comunicações Móveis (RSCM) — 2026/2027
Universidade de Trás-os-Montes e Alto Douro (UTAD)

Funcionalidades (Protocolo Semana 7):
- Observabilidade em sistemas de telecomunicações:
  Registo automático de timestamp, porta, linha AT, resposta, estado interno e latência (ms).
- Logging estruturado duplo em formato JSON (JSON Lines + JSON) e CSV.
- Geração automática de sumário/relatório de métricas de síntese a partir dos logs:
  * Nº de SMS enviados e recebidos
  * Taxa de erros global e por comando
  * Estatísticas de latência por comando (mínima, média, máxima e contagem)
"""

import csv
import json
import os
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional


DEFAULT_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
DEFAULT_CSV_PATH = os.path.join(DEFAULT_LOG_DIR, "telemetria_at.csv")
DEFAULT_JSON_PATH = os.path.join(DEFAULT_LOG_DIR, "telemetria_at.json")
DEFAULT_SUMMARY_PATH = os.path.join(DEFAULT_LOG_DIR, "sumario_telemetria.md")


class TelemetryLogger:
    """Gere o registo estruturado (JSON/CSV) e cálculo de métricas de telemetria do TP1."""

    CSV_FIELDS = [
        "timestamp",
        "port",
        "event_type",
        "at_command",
        "response",
        "status",
        "internal_state",
        "network_profile",
        "latency_ms"
    ]

    def __init__(
        self,
        csv_path: str = DEFAULT_CSV_PATH,
        json_path: str = DEFAULT_JSON_PATH,
        summary_path: str = DEFAULT_SUMMARY_PATH
    ):
        self.csv_path = csv_path
        self.json_path = json_path
        self.summary_path = summary_path
        self._lock = threading.Lock()
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        log_dir = os.path.dirname(self.csv_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        if not os.path.exists(self.csv_path):
            with open(self.csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                writer.writeheader()

        if not os.path.exists(self.json_path):
            with open(self.json_path, mode="w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def log_event(
        self,
        port: str,
        at_command: str,
        response: str,
        status: str,
        internal_state: str,
        latency_ms: float = 0.0,
        network_profile: str = "LTE",
        event_type: str = "COMMAND"
    ) -> Dict[str, Any]:
        """
        Regista uma interação AT ou evento assíncrono (URC) nos ficheiros CSV e JSON.
        """
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "port": str(port),
            "event_type": event_type,  # "COMMAND", "SMS_TX", "SMS_RX_URC", "CDS_URC"
            "at_command": str(at_command),
            "response": str(response),
            "status": str(status),      # "OK", "ERROR", "PROMPT", "URC", "TIMEOUT"
            "internal_state": str(internal_state),
            "network_profile": str(network_profile),
            "latency_ms": round(float(latency_ms), 2)
        }

        with self._lock:
            self._ensure_log_dir()

            # 1. Acrescentar ao CSV
            try:
                with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                    writer.writerow(entry)
            except Exception as e:
                print(f"[TELEMETRIA] Aviso ao gravar CSV: {e}")

            # 2. Atualizar ficheiro JSON estruturado
            try:
                records = self._read_json_unlocked()
                records.append(entry)
                with open(self.json_path, mode="w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[TELEMETRIA] Aviso ao gravar JSON: {e}")

        return entry

    def _read_json_unlocked(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.json_path):
            return []
        try:
            with open(self.json_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def load_logs(self) -> List[Dict[str, Any]]:
        """Lê todos os registos de telemetria a partir do ficheiro JSON (ou CSV em fallback)."""
        with self._lock:
            records = self._read_json_unlocked()
            if records:
                return records

            if os.path.exists(self.csv_path):
                try:
                    with open(self.csv_path, mode="r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        out = []
                        for row in reader:
                            row["latency_ms"] = float(row.get("latency_ms", 0.0) or 0.0)
                            out.append(row)
                        return out
                except Exception:
                    return []
            return []

    def clear_logs(self):
        """Limpa os ficheiros de log (CSV e JSON) para iniciar uma nova sessão limpa."""
        with self._lock:
            log_dir = os.path.dirname(self.csv_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            with open(self.csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                writer.writeheader()
            with open(self.json_path, mode="w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    @staticmethod
    def _normalize_cmd_key(cmd: str) -> str:
        """Agrupa comandos AT pela sua família (ex: AT+CMGS="+351..." -> AT+CMGS)."""
        c = cmd.strip().upper()
        if not c:
            return "OUTRO"
        if c == "SMS_BODY" or c == "RAW_SMS_BODY":
            return "AT+CMGS (BODY)"
        if c.endswith("=?"):
            return c
        if "?" in c:
            base = c.split("?", 1)[0]
            return base + "?"
        if "=" in c:
            return c.split("=", 1)[0]
        return c

    def compute_metrics(self, logs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Calcula o sumário automático de métricas a partir dos logs registados:
        - Nº de SMS enviados e recebidos
        - Total de comandos, sucessos, erros e taxa de erro (%)
        - Latências (média, mínima, máxima) global e discriminada por comando AT
        """
        records = logs if logs is not None else self.load_logs()

        total_events = len(records)
        command_records = [r for r in records if r.get("event_type") in ("COMMAND", "SMS_TX")]
        total_commands = len(command_records)

        error_count = 0
        ok_count = 0
        sms_sent = 0
        sms_received = 0
        cds_reports = 0

        cmd_stats: Dict[str, Dict[str, Any]] = {}
        state_counts: Dict[str, int] = {}

        for r in records:
            ev_type = r.get("event_type", "COMMAND")
            cmd_raw = str(r.get("at_command", ""))
            resp_raw = str(r.get("response", ""))
            status = str(r.get("status", "OK")).upper()
            state = str(r.get("internal_state", "UNKNOWN"))
            lat = float(r.get("latency_ms", 0.0) or 0.0)

            state_counts[state] = state_counts.get(state, 0) + 1

            # Contabilizar SMS recebidos e relatórios +CDS
            if ev_type == "SMS_RX_URC" or "+CMTI:" in resp_raw or cmd_raw.upper().startswith("AT#INJECT_SMS"):
                if ev_type == "SMS_RX_URC":
                    sms_received += 1
            if ev_type == "CDS_URC" or "+CDS:" in resp_raw:
                if ev_type == "CDS_URC":
                    cds_reports += 1

            if ev_type not in ("COMMAND", "SMS_TX"):
                continue

            is_err = (
                status in ("ERROR", "TIMEOUT")
                or "ERROR" in resp_raw.upper()
                or "TIMEOUT" in resp_raw.upper()
            )
            if is_err:
                error_count += 1
            else:
                ok_count += 1

            # Contabilizar SMS enviados com sucesso (+CMGS: <mr>)
            if ("+CMGS:" in resp_raw) and not is_err:
                sms_sent += 1

            cmd_key = self._normalize_cmd_key(cmd_raw)
            if cmd_key not in cmd_stats:
                cmd_stats[cmd_key] = {
                    "count": 0,
                    "ok": 0,
                    "errors": 0,
                    "latencies": []
                }
            cmd_stats[cmd_key]["count"] += 1
            if is_err:
                cmd_stats[cmd_key]["errors"] += 1
            else:
                cmd_stats[cmd_key]["ok"] += 1
            if lat > 0:
                cmd_stats[cmd_key]["latencies"].append(lat)

        # Fallback: se os SMS recebidos foram injetados via AT#INJECT_SMS com sucesso e não duplicados por URC
        if sms_received == 0:
            for r in records:
                if str(r.get("at_command", "")).upper().startswith("AT#INJECT_SMS") and "#INJECT: OK" in str(r.get("response", "")):
                    sms_received += 1

        all_latencies = [
            float(r.get("latency_ms", 0.0))
            for r in command_records
            if float(r.get("latency_ms", 0.0) or 0.0) > 0
        ]
        avg_latency_ms = (sum(all_latencies) / len(all_latencies)) if all_latencies else 0.0
        min_latency_ms = min(all_latencies) if all_latencies else 0.0
        max_latency_ms = max(all_latencies) if all_latencies else 0.0

        error_rate_pct = (error_count / total_commands * 100.0) if total_commands > 0 else 0.0

        per_command_summary = {}
        for k, data in sorted(cmd_stats.items()):
            lats = data["latencies"]
            per_command_summary[k] = {
                "count": data["count"],
                "ok": data["ok"],
                "errors": data["errors"],
                "error_rate_pct": round((data["errors"] / data["count"] * 100.0) if data["count"] else 0.0, 1),
                "avg_ms": round(sum(lats) / len(lats), 2) if lats else 0.0,
                "min_ms": round(min(lats), 2) if lats else 0.0,
                "max_ms": round(max(lats), 2) if lats else 0.0
            }

        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_events": total_events,
            "total_commands": total_commands,
            "ok_count": ok_count,
            "error_count": error_count,
            "error_rate_pct": round(error_rate_pct, 2),
            "sms_sent": sms_sent,
            "sms_received": sms_received,
            "cds_reports": cds_reports,
            "avg_latency_ms": round(avg_latency_ms, 2),
            "min_latency_ms": round(min_latency_ms, 2),
            "max_latency_ms": round(max_latency_ms, 2),
            "state_distribution": state_counts,
            "per_command": per_command_summary
        }

    def generate_summary_report(self, save_to_file: bool = True) -> str:
        """Gera um relatório formatado (Markdown/Texto) a partir dos logs e grava em disco."""
        m = self.compute_metrics()

        lines = [
            "# Sumário Automático de Telemetria e Registo (Semana 7 - Checkpoint TP1)",
            f"**Data de Geração:** {m['generated_at']}  ",
            f"**Ficheiro CSV:** `{self.csv_path}`  ",
            f"**Ficheiro JSON:** `{self.json_path}`",
            "",
            "## 1. Métricas Globais de Síntese",
            f"- **Total de Eventos Registados:** {m['total_events']}",
            f"- **Total de Comandos AT Executados:** {m['total_commands']} (Sucesso: {m['ok_count']} | Erros: {m['error_count']})",
            f"- **Taxa Global de Erros:** {m['error_rate_pct']:.2f}%",
            f"- **Nº de SMS Enviados (+CMGS):** {m['sms_sent']}",
            f"- **Nº de SMS Recebidos (+CMTI):** {m['sms_received']}",
            f"- **Relatórios de Entrega (+CDS):** {m['cds_reports']}",
            f"- **Latência Global (Mín / Média / Máx):** {m['min_latency_ms']:.1f} ms / {m['avg_latency_ms']:.1f} ms / {m['max_latency_ms']:.1f} ms",
            "",
            "## 2. Latências e Taxa de Erros por Comando AT",
            "| Comando AT | Execuções | Sucessos | Erros | Taxa Erro (%) | Lat. Mín (ms) | Lat. Média (ms) | Lat. Máx (ms) |",
            "|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"
        ]

        if not m["per_command"]:
            lines.append("| *(Sem comandos registados)* | 0 | 0 | 0 | 0.0% | 0.0 | 0.0 | 0.0 |")
        else:
            for cmd, info in m["per_command"].items():
                lines.append(
                    f"| `{cmd}` | {info['count']} | {info['ok']} | {info['errors']} | "
                    f"{info['error_rate_pct']:.1f}% | {info['min_ms']:.1f} | {info['avg_ms']:.1f} | {info['max_ms']:.1f} |"
                )

        lines.append("")
        lines.append("## 3. Distribuição de Eventos por Estado Interno do Modem")
        lines.append("| Estado Interno | Ocorrências |")
        lines.append("|:---|:---:|")
        if not m["state_distribution"]:
            lines.append("| *(Sem dados)* | 0 |")
        else:
            for st, cnt in sorted(m["state_distribution"].items()):
                lines.append(f"| `{st}` | {cnt} |")

        report_text = "\n".join(lines) + "\n"

        if save_to_file:
            try:
                self._ensure_log_dir()
                with open(self.summary_path, mode="w", encoding="utf-8") as f:
                    f.write(report_text)
            except Exception as e:
                print(f"[TELEMETRIA] Aviso ao gravar sumário: {e}")

        return report_text


# Instância partilhada por omissão
default_telemetry = TelemetryLogger()


if __name__ == "__main__":
    print("=" * 75)
    print(" RSCM 2026/2027 - GERADOR DE SUMARIO DE TELEMETRIA (SEMANA 7)")
    print("=" * 75)
    report = default_telemetry.generate_summary_report(save_to_file=True)
    print(report)
    print("=" * 75)
    print(f"Relatorio guardado em: {default_telemetry.summary_path}")
