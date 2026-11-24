#!/usr/bin/env python3
"""
painel_c.py - Painel web (graficos em tempo real) para o controlador em C.

Quem controla o motor e o pid_motor (C, Ts = 20 ms). Este programa NAO usa os
GPIO: so serve a pagina do painel (painel.html, nesta pasta)
e faz a ponte com o pid_motor por UDP local:
  - recebe a telemetria do pid_motor na porta 5005 (uma linha por amostra);
  - repassa os comandos da pagina (manual / pid / parar) para a porta 5006;
  - manda um "ping" a cada 0,5 s. Se o painel fechar, o pid_motor para o motor
    em 2 s.

Uso, na Pi, em dois terminais:
  1) cd ~/Controle2/controle_c && ./pid_motor        (fica parado esperando)
  2) cd ~/Controle2/controle_c && python3 painel_c.py
Abrir: http://localhost:8000 na Pi, ou pelo tunel SSH no PC (ver README).
Os ensaios sao gravados pelo pid_motor (CSV com cabecalho, um por ensaio).
"""

import json
import os
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORTA_HTTP = 8000
PORTA_TELEMETRIA = 5005      # pid_motor -> painel
PORTA_COMANDOS = 5006        # painel -> pid_motor
DUTY_MAX = 50.0              # o mesmo do pid_motor.c (o limite vale la, no C)
HISTORICO_MAX = 15000        # amostras na memoria (5 min a 50 Hz)

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_HTML = os.path.join(PASTA, "painel.html")


class Ponte:
    """Guarda a telemetria do pid_motor e envia os comandos para ele."""

    def __init__(self):
        self.trava = threading.Lock()
        self.historico = deque(maxlen=HISTORICO_MAX)
        self.estado = {"t": 0.0, "modo": "parado", "setpoint": 0.0, "rpm": 0.0,
                       "duty": 0.0, "erro": 0.0, "kp": 1.5, "ki": 7.5, "kd": 0.0,
                       "aviso": 0, "arquivo": ""}
        self.ultimo_rx = 0.0
        self.mensagem = "Esperando o pid_motor..."

        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", PORTA_TELEMETRIA))
        self.rx.settimeout(0.5)
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        threading.Thread(target=self._receber, daemon=True).start()
        threading.Thread(target=self._ping, daemon=True).start()

    def _enviar(self, texto):
        self.tx.sendto(texto.encode(), ("127.0.0.1", PORTA_COMANDOS))

    def _ping(self):
        while True:
            self._enviar("ping")
            time.sleep(0.5)

    def _receber(self):
        while True:
            try:
                dados = self.rx.recv(512).decode()
            except socket.timeout:
                continue
            c = dados.strip().split(",")
            if len(c) < 11:
                continue
            try:
                e = {"t": float(c[0]), "modo": c[1], "setpoint": float(c[2]),
                     "rpm": float(c[3]), "duty": float(c[4]), "erro": float(c[5]),
                     "kp": float(c[6]), "ki": float(c[7]), "kd": float(c[8]),
                     "aviso": int(c[9]), "arquivo": ",".join(c[10:])}
            except ValueError:
                continue
            em_pid = e["modo"] == "pid"
            with self.trava:
                if e["t"] < self.estado["t"]:
                    self.historico.clear()        # pid_motor reiniciado
                self.estado = e
                self.ultimo_rx = time.monotonic()
                self.historico.append((e["t"], e["setpoint"] if em_pid else None,
                                       round(e["rpm"], 2), round(e["duty"], 2),
                                       round(e["erro"], 2) if em_pid else None))

    def comando(self, dados):
        acao = dados.get("acao")
        try:
            if acao == "parar":
                self._enviar("parar")
                self.mensagem = "Motor parado."
            elif acao == "manual":
                duty = float(dados["duty"])
                if not 0 <= duty <= 100:
                    raise ValueError("O duty deve estar entre 0 e 100.")
                self._enviar(f"manual {duty}")
                self.mensagem = f"Malha aberta: duty {min(duty, DUTY_MAX):.1f}%"
                if duty > DUTY_MAX:
                    self.mensagem += f" (limitado por DUTY_MAX = {DUTY_MAX:g}%)"
            elif acao == "pid":
                sp, kp, ki, kd = (float(dados[k]) for k in ("setpoint", "kp", "ki", "kd"))
                if sp <= 0 or min(kp, ki, kd) < 0:
                    raise ValueError("O setpoint deve ser maior que 0 e os ganhos, "
                                     "maiores ou iguais a 0.")
                if kp == ki == kd == 0:
                    raise ValueError("Informe ao menos um ganho maior que zero.")
                self._enviar(f"pid {sp} {kp} {ki} {kd}")
                self.mensagem = (f"PID (C) ativo: setpoint {sp:g} RPM | "
                                 f"Kp={kp:g} Ki={ki:g} Kd={kd:g}")
            else:
                raise ValueError("Comando desconhecido.")
        except KeyError:
            self.mensagem = "Comando incompleto."
        except ValueError as exc:
            self.mensagem = str(exc)
        return {"mensagem": self.mensagem}

    def dados(self, desde):
        with self.trava:
            e = self.estado
            conectado = time.monotonic() - self.ultimo_rx < 1.0
            if not conectado:
                msg = ("Sem dados do pid_motor. Ele esta rodando? "
                       "(cd ~/Controle2/controle_c && ./pid_motor)")
            elif e["aviso"]:
                msg = "Velocidade negativa no PID: motor parado. Confira SINAL_ENCODER."
            else:
                msg = self.mensagem
            return {
                "t_atual": e["t"], "modo": e["modo"], "unidade": "RPM",
                "velocidade": e["rpm"], "setpoint": e["setpoint"], "duty": e["duty"],
                "erro": e["erro"], "kp": e["kp"], "ki": e["ki"], "kd": e["kd"],
                "duty_max": DUTY_MAX, "pid_disponivel": conectado,
                "mensagem": msg, "arquivo": e["arquivo"],
                "amostras": [a for a in self.historico if a[0] > desde],
            }


def criar_handler(ponte):
    class Handler(BaseHTTPRequestHandler):
        def _enviar(self, corpo, tipo, codigo=200):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                with open(ARQUIVO_HTML, "rb") as f:
                    self._enviar(f.read(), "text/html; charset=utf-8")
            elif url.path == "/dados":
                try:
                    desde = float(parse_qs(url.query).get("desde", ["-1"])[0])
                except ValueError:
                    desde = -1.0
                self._enviar(json.dumps(ponte.dados(desde)).encode(), "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/comando":
                self.send_error(404)
                return
            n = int(self.headers.get("Content-Length", 0))
            try:
                dados = json.loads(self.rfile.read(n))
            except ValueError:
                dados = {}
            self._enviar(json.dumps(ponte.comando(dados)).encode(), "application/json")

        def log_message(self, *args):
            pass   # Nao poluir o terminal com cada requisicao

    return Handler


def main():
    ponte = Ponte()
    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA_HTTP), criar_handler(ponte))
    nome = socket.gethostname().lower()
    print(f"Painel (C) no ar: http://localhost:{PORTA_HTTP} (na Pi) "
          f"ou http://{nome}.local:{PORTA_HTTP} (na rede)")
    print("Ctrl+C para encerrar (o pid_motor para o motor em 2 s sem o painel).")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        try:
            ponte.comando({"acao": "parar"})
        except OSError:
            pass
        print("\nPainel encerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
