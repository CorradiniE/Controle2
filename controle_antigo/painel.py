#!/usr/bin/env python3
"""
painel.py - Painel web de monitoramento e controle do motor.

Roda o laco de controle com periodo fixo e serve uma pagina com graficos
em tempo real. Precisa do arquivo painel.html na mesma pasta.

Acesso (o painel.py precisa estar rodando):
  - Navegador da propria Pi:        http://localhost:8000
  - Pela rede:                      http://<hostname>.local:8000
                                    (nesta Pi: http://rasp4.local:8000)
  - PC via tunel SSH:               ssh -L 8000:localhost:8000 usuario@IP_DA_PI
                                    e abrir http://localhost:8000 no PC

Modos:
  parado - motor desligado (a velocidade continua sendo medida)
  manual - malha aberta: duty fixo escolhido no painel
  pid    - malha fechada: o PID calcula o duty a cada periodo

Cada ensaio (manual ou PID) e gravado em CSV na pasta pid/dados/ do
repositorio, com um cabecalho de comentarios (#) descrevendo as condicoes.
Calibracao e sinal do encoder ficam em hardware.py.
Encerrar com Ctrl+C (o motor e parado automaticamente).
"""

import csv
import json
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import lgpio

from hardware import (CHIP, CONTAGENS_POR_VOLTA, DUTY_MAX, SINAL_ENCODER, Encoder,
                      Motor, contagens_para_rpm)
from pid import PID

# ---------------- Configuracao ----------------
PERIODO = 0.05              # Periodo de amostragem do controle, em s (20 Hz)
PORTA = 8000
HISTORICO_MAX = 6000        # Amostras mantidas na memoria (5 min a 20 Hz)

PASTA = os.path.dirname(os.path.abspath(__file__))
PASTA_ENSAIOS = os.path.normpath(os.path.join(PASTA, "..", "pid", "dados"))
ARQUIVO_HTML = os.path.join(PASTA, "painel.html")


class Controlador:
    def __init__(self):
        self.h = lgpio.gpiochip_open(CHIP)
        self.motor = Motor(self.h)
        self.enc = Encoder(self.h)
        self.pid = PID(kp=0.0, ki=0.0, kd=0.0, periodo=PERIODO,
                       saida_min=0.0, saida_max=DUTY_MAX)
        self.unidade = "RPM"

        self.trava = threading.Lock()
        self.modo = "parado"
        self.setpoint = 0.0
        self.duty = 0.0
        self.velocidade = 0.0
        self.erro = 0.0
        self.mensagem = "Pronto."
        self.historico = deque(maxlen=HISTORICO_MAX)
        self.t0 = time.monotonic()
        self.t_atual = 0.0

        self.arquivo = None
        self.escritor = None
        self.nome_arquivo = ""

        self.rodando = True
        self.thread = threading.Thread(target=self._laco, daemon=True)
        self.thread.start()

    # ---------- Laco de controle (periodo fixo) ----------
    def _laco(self):
        proximo = time.monotonic()
        c_ant, t_ant = self.enc.contagem(), proximo
        while self.rodando:
            # Agenda pelo relogio, nao pela velocidade do codigo
            proximo += PERIODO
            espera = proximo - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            else:
                proximo = time.monotonic()   # Atrasou: ressincroniza sem acumular

            # Medicao: contagens no intervalo -> velocidade
            agora = time.monotonic()
            c = self.enc.contagem()
            vel = contagens_para_rpm((c - c_ant) / (agora - t_ant))
            c_ant, t_ant = c, agora

            with self.trava:
                self.velocidade = vel
                if self.modo == "pid":
                    if vel < -10:
                        # Realimentacao com sinal trocado faria o PID disparar
                        self._parar("Velocidade negativa no modo PID. "
                                    "Troque SINAL_ENCODER em hardware.py.")
                    else:
                        self.erro = self.setpoint - vel
                        u = self.pid.atualizar(self.setpoint, vel)
                        self.duty = self.motor.definir_duty(u)

                t = round(agora - self.t0, 3)
                self.t_atual = t
                em_pid = self.modo == "pid"
                sp = self.setpoint if em_pid else None
                erro = round(self.erro, 2) if em_pid else None
                self.historico.append((t, sp, round(vel, 2), round(self.duty, 2), erro))

                if self.escritor:
                    self.escritor.writerow([
                        t, self.modo, "" if sp is None else sp, round(vel, 3),
                        round(self.duty, 3), "" if erro is None else erro,
                        self.pid.kp, self.pid.ki, self.pid.kd])

    # ---------- Ensaios em CSV ----------
    def _iniciar_ensaio(self, modo):
        self._fechar_ensaio()
        os.makedirs(PASTA_ENSAIOS, exist_ok=True)
        self.nome_arquivo = f"{modo}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        caminho = os.path.join(PASTA_ENSAIOS, self.nome_arquivo)
        self.arquivo = open(caminho, "w", newline="", buffering=1)
        # Cabecalho com as condicoes do ensaio (linhas '#' sao ignoradas na analise)
        self.arquivo.write(
            f"# Ensaio {modo} - {datetime.now():%Y-%m-%d %H:%M:%S} - painel v0\n"
            f"# Ts nominal = {PERIODO} s | DUTY_MAX = {DUTY_MAX} % | "
            f"CONTAGENS_POR_VOLTA = {CONTAGENS_POR_VOLTA} | "
            f"SINAL_ENCODER = {SINAL_ENCODER}\n"
            f"# Ganhos do PID: colunas kp, ki, kd (registradas a cada amostra)\n"
            f"# Condicoes/observacoes: (anotar aqui: carga, fonte, perturbacoes...)\n")
        self.escritor = csv.writer(self.arquivo)
        self.escritor.writerow(["tempo_s", "modo", "setpoint", f"velocidade_{self.unidade}",
                                "duty_pct", "erro", "kp", "ki", "kd"])

    def _fechar_ensaio(self):
        if self.arquivo:
            self.arquivo.close()
        self.arquivo = None
        self.escritor = None
        self.nome_arquivo = ""

    # ---------- Comandos vindos da pagina ----------
    def _parar(self, mensagem):
        self.motor.parar()
        self.modo = "parado"
        self.duty = 0.0
        self.erro = 0.0
        self._fechar_ensaio()
        self.mensagem = mensagem

    def comando(self, dados):
        acao = dados.get("acao")
        with self.trava:
            try:
                if acao == "parar":
                    self._parar("Motor parado.")

                elif acao == "manual":
                    duty = float(dados["duty"])
                    if not 0 <= duty <= 100:
                        raise ValueError("O duty deve estar entre 0 e 100.")
                    if self.modo != "manual":
                        if self.modo == "parado":
                            self.motor.definir_sentido(+1)
                        self.modo = "manual"
                        self._iniciar_ensaio("manual")
                    self.duty = self.motor.definir_duty(duty)
                    self.mensagem = f"Malha aberta: duty {self.duty:.1f}%"
                    if self.duty < duty:
                        self.mensagem += f" (limitado por DUTY_MAX = {DUTY_MAX}%)"

                elif acao == "pid":
                    sp, kp, ki, kd = (float(dados[k]) for k in ("setpoint", "kp", "ki", "kd"))
                    if sp <= 0 or min(kp, ki, kd) < 0:
                        raise ValueError("O setpoint deve ser maior que 0 e os ganhos, "
                                         "maiores ou iguais a 0.")
                    if kp == ki == kd == 0:
                        raise ValueError("Informe ao menos um ganho maior que zero.")
                    self.pid.kp, self.pid.ki, self.pid.kd = kp, ki, kd
                    if self.modo != "pid":
                        duty_inicial = self.duty if self.modo == "manual" else 0.0
                        if self.modo == "parado":
                            self.motor.definir_sentido(+1)
                        self.pid.reiniciar(integral_inicial=duty_inicial)
                        self.modo = "pid"
                        self._iniciar_ensaio("pid")
                    self.setpoint = sp
                    self.mensagem = (f"PID ativo: setpoint {sp:g} RPM | "
                                     f"Kp={kp:g} Ki={ki:g} Kd={kd:g}")

                else:
                    raise ValueError("Comando desconhecido.")

            except KeyError:
                self.mensagem = "Comando incompleto."
            except ValueError as exc:
                self.mensagem = str(exc)
            return {"mensagem": self.mensagem}

    def estado(self, desde):
        with self.trava:
            return {
                "t_atual": self.t_atual,
                "modo": self.modo,
                "unidade": self.unidade,
                "velocidade": self.velocidade,
                "setpoint": self.setpoint,
                "duty": self.duty,
                "erro": self.erro,
                "kp": self.pid.kp, "ki": self.pid.ki, "kd": self.pid.kd,
                "duty_max": DUTY_MAX,
                "pid_disponivel": True,
                "mensagem": self.mensagem,
                "arquivo": self.nome_arquivo,
                "amostras": [a for a in self.historico if a[0] > desde],
            }

    def fechar(self):
        self.rodando = False
        self.thread.join(timeout=1)
        with self.trava:
            self._parar("Encerrado.")
        self.motor.fechar()
        self.enc.fechar()
        lgpio.gpiochip_close(self.h)


def criar_handler(ctrl):
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
                corpo = json.dumps(ctrl.estado(desde)).encode()
                self._enviar(corpo, "application/json")
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
            corpo = json.dumps(ctrl.comando(dados)).encode()
            self._enviar(corpo, "application/json")

        def log_message(self, *args):
            pass   # Nao poluir o terminal com cada requisicao

    return Handler


def main():
    ctrl = Controlador()
    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA), criar_handler(ctrl))
    nome = socket.gethostname().lower()
    print(f"Painel no ar: http://localhost:{PORTA} (na Pi) "
          f"ou http://{nome}.local:{PORTA} (na rede)")
    print(f"Ensaios gravados em: {PASTA_ENSAIOS}")
    print("Ctrl+C para encerrar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        servidor.server_close()
        ctrl.fechar()
        print("Motor parado e GPIO liberados.")


if __name__ == "__main__":
    main()
