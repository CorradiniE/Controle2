#!/usr/bin/env python3
"""
roteiro_ganhos.py - Previsão, por simulação, do comportamento de cada conjunto
de ganhos do roteiro de ensaios do PID.

Planta: modelo identificado no ensaio de malha aberta de 2026-11-19
(pid/dados/2026-11-19_malha_aberta_degrau_20a35.csv, método dos dois pontos):
    G(s) = 2,17 e^(-0,036 s) / (0,221 s + 1)     [RPM/%]
linearizado em torno de 20 % de duty -> 10,8 RPM.

Ensaio simulado (igual ao roteiro na bancada): motor em manual a 20 %, liga o
PID com setpoint de 40 RPM, partida sem tranco (integral = 20 %), saturação
de 0 a DUTY_MAX = 50 %. Controlador: o PID do controle_c/pid_motor.c (cópia em
pid_c.py), com Ts = 20 ms.
Também roda com ruído de medição de 0,5 RPM (desvio medido a 35 %) para ver
quanto cada ganho amplifica o ruído no duty.

Uso:  python pid/analise/roteiro_ganhos.py
Saída: tabela no terminal e em pid/analise/resultados/roteiro_ganhos.txt
"""

import os
import random
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import identificacao_zn as iz  # noqa: E402

K, TAU, THETA, T = 2.17, 0.221, 0.036, 0.02
Y0, U0, SETPOINT, DUTY_MAX = 10.8, 20.0, 40.0, 50.0
RUIDO = 0.5          # RPM, desvio da velocidade medido em regime a 35 %
DURACAO = 8.0        # s

# (ensaio, grupo, Kp, Ki, Kd, o que observar)
ROTEIRO = [
    ("A1", "Só P", 0.3, 0, 0, "lento, sem overshoot, erro em regime grande"),
    ("A2", "Só P", 1.0, 0, 0, "mais rápido, erro em regime menor"),
    ("A3", "Só P", 3.0, 0, 0, "overshoot pequeno, ainda com erro, duty ruidoso"),
    ("A4", "Só P", 8.0, 0, 0, "oscilação sustentada (ganho demais)"),
    ("B1", "PI, Ki varia", 1.5, 1.0, 0, "sem overshoot, chega devagar (integral lenta)"),
    ("B2", "PI, Ki varia", 1.5, 3.0, 0, "sem overshoot, mais rápido"),
    ("B3", "PI, Ki varia", 1.5, 7.5, 0, "referência (ZN p/ Ts 50 ms, validado): sem overshoot"),
    ("B4", "PI, Ki varia", 1.5, 30.0, 0, "overshoot moderado (~10 %)"),
    ("B5", "PI, Ki varia", 1.5, 35.0, 0, "overshoot maior e oscilação que demora a sumir"),
    ("B6", "PI, Ki varia", 1.5, 40.0, 0, "oscilação sustentada (integral demais)"),
    ("C1", "PI, Kp varia", 0.3, 7.5, 0, "overshoot grande e lento (pouco Kp para o Ki)"),
    ("C2", "PI, Kp varia", 0.7, 7.5, 0, "overshoot médio"),
    ("C3", "PI, Kp varia", 4.0, 7.5, 0, "Kp alto: oscila e o duty fica ruidoso"),
    ("D1", "PID, Kd varia", 1.5, 7.5, 0.05, "quase igual ao B3, duty um pouco mais ruidoso"),
    ("D2", "PID, Kd varia", 1.5, 7.5, 0.1, "derivada amplifica o ruído"),
    ("D3", "PID, Kd varia", 1.5, 7.5, 0.2, "overshoot e duty ruidoso"),
    ("D4", "PID, Kd varia", 1.5, 7.5, 0.3, "Kd demais: oscila"),
    ("Z1", "ZN p/ Ts 20 ms", 2.01, 13.24, 0, "PI de Ziegler-Nichols refeito p/ o C (theta + Ts/2)"),
    ("Z2", "ZN p/ Ts 20 ms", 2.68, 29.39, 0.061, "PID de Ziegler-Nichols p/ o C"),
]


def simular(kp, ki, kd, ruido=0.0, semente=3):
    rnd = random.Random(semente)
    gz = iz.discretizar_zoh(K, TAU, THETA, T)
    pid = iz.carregar_pid()(kp, ki, kd, periodo=T, saida_min=0.0, saida_max=DUTY_MAX)
    pid.reiniciar(integral_inicial=U0, erro_inicial=SETPOINT - Y0)
    planta = iz.PlantaDiscreta(gz, Y0, U0)
    y, ys, us = Y0, [], []
    for _ in range(int(DURACAO / T)):
        u = pid.atualizar(SETPOINT, y + (rnd.gauss(0, ruido) if ruido else 0.0))
        ys.append(y)
        us.append(u)
        y = planta.passo(u)
    return ys, us


def metricas(ys, us):
    amp = SETPOINT - Y0
    n = len(ys) // 5                      # último 1/5 = regime
    yf = sum(ys[-n:]) / n
    sobre = max(0.0, 100 * (max(ys) - SETPOINT) / amp)
    t5 = None                             # acomodação na faixa de 5 % em torno do final
    for k in range(len(ys) - 1, -1, -1):
        if abs(ys[k] - yf) > 0.05 * amp:
            t5 = (k + 1) * T if k + 1 < len(ys) else None
            break
    else:
        t5 = 0.0
    return {"sobre": sobre, "t5": t5, "erro": SETPOINT - yf,
            "osc": max(ys[-n:]) - min(ys[-n:]), "duty_pp": max(us[-n:]) - min(us[-n:])}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    linhas = [
        f"Roteiro de ganhos - previsão por simulação (setpoint {SETPOINT:g} RPM, "
        f"partida de {U0:g} % / {Y0:g} RPM, DUTY_MAX {DUTY_MAX:g} %)",
        f"Planta: G(s) = {K} e^(-{THETA} s)/({TAU} s + 1), Ts = {T} s",
        "",
        f"{'ens.':<5}{'Kp':>5}{'Ki':>6}{'Kd':>6} |{'overshoot':>10}{'acomod.5%':>11}"
        f"{'erro reg.':>10}{'oscil.':>8} |{'duty p-p c/ ruído':>18} | o que observar",
    ]
    for ens, _, kp, ki, kd, obs in ROTEIRO:
        m = metricas(*simular(kp, ki, kd))
        mr = metricas(*simular(kp, ki, kd, ruido=RUIDO))
        t5 = "não" if m["t5"] is None or m["osc"] > 0.05 * (SETPOINT - Y0) else f"{m['t5']:.2f} s"
        linhas.append(
            f"{ens:<5}{kp:>5g}{ki:>6g}{kd:>6g} |{m['sobre']:>9.1f}%{t5:>11}"
            f"{m['erro']:>10.2f}{m['osc']:>8.1f} |{mr['duty_pp']:>16.1f} % | {obs}")
    linhas += ["", "overshoot em % do degrau (40 - 10,8 RPM); erro reg. e oscil. em RPM;",
               "duty p-p = variação pico a pico do duty em regime com ruído de "
               f"{RUIDO} RPM na medida.",
               "Modelo linear: não inclui zona morta nem atrito. Confirme na bancada."]
    texto = "\n".join(linhas)
    print(texto)
    pasta = os.path.join(AQUI, "resultados")
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "roteiro_ganhos.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")


if __name__ == "__main__":
    main()
