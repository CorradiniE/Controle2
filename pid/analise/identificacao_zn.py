#!/usr/bin/env python3
"""
identificacao_zn.py - Modelo da planta pela curva de reação e sintonia do PID
por Ziegler-Nichols (método da curva de reação, em malha aberta).

Base bibliográfica
------------------
- Razali et al. (2019): o método usado aqui. Aplica-se um degrau de PWM em malha
  aberta, registra-se a velocidade (curva de reação) e dela se tiram:
      delta = amplitude do degrau na entrada (duty, %)
      Delta = variação da saída em regime (RPM)
      S     = inclinação máxima da curva de saída
  Com isso se monta o modelo de 1ª ordem com atraso (Eq. 1 do artigo):
      G(s) = Kp * e^(-theta*s) / (tau*s + 1),  com  Kp = Delta/delta,  tau = Delta/S
  e os ganhos saem da Tabela II do artigo (Ziegler-Nichols, curva de reação):
      P   : Kc = (1/Kp)(tau/t0)
      PI  : Kc = (0.9/Kp)(tau/t0),  Ti = 3.33*t0
      PID : Kc = (1.2/Kp)(tau/t0),  Ti = 2*t0,  Td = 0.5*t0
  em que t0 = theta é o tempo morto.
- Herrera-Aristizábal et al. (2020): modelo físico do motor controlado pela
  armadura (Eq. 10):
      G(s) = Kt / (La*J*s^2 + (La*B + Ra*J)*s + Ra*B + Kt*Ke)
  Como La é pequena, o polo elétrico fica muito mais rápido que o mecânico e o
  sistema se comporta como de 1ª ordem. No próprio exemplo numérico do artigo
  (Eq. 12), os polos ficam em cerca de -0,57 e -8068 rad/s. Isso justifica
  aproximar a nossa planta pelo modelo de 1ª ordem com atraso de Razali et al.
  sem precisar medir J, B, Ra e La.
- Kolya et al. (2021): acionamento do motor DC pela Raspberry Pi com ponte H e
  PWM no enable, em malha aberta. É o mesmo arranjo de acionamento usado aqui.

O que o script faz
------------------
1. Lê um CSV de ensaio em malha aberta (formato dos painéis em C e em Python:
   tempo_s, modo, setpoint, velocidade_<unidade>, duty_pct, ...).
2. Encontra o degrau de duty e mede o Ts real (média, desvio e extremos, ou seja,
   o jitter do laço).
3. Identifica K, tau e theta por dois métodos:
     - tangente no ponto de inclinação máxima (o de Razali et al.);
     - dois pontos, 28,3 % e 63,2 % (Smith), como comparação, porque é menos
       sensível ao ruído do encoder.
   Para cada método, calcula o "fit" do modelo contra os dados.
4. Calcula os ganhos P, PI e PID pela Tabela II e converte para a forma usada
   no controlador (controle_c/pid_motor.c): Kp = Kc, Ki = Kc/Ti, Kd = Kc*Td.
5. Discretiza G(s) com segurador de ordem zero (ZOH), no Ts do projeto,
   tratando atraso fracionário:
       G(z) = z^-d * (b1*z^-1 + b2*z^-2) / (1 - a*z^-1)
6. Simula a malha fechada com o PID do controlador em C (cópia em pid_c.py:
   saturação, anti-windup e filtro da derivada) e mostra sobressinal, tempo
   de acomodação e erro em regime.
7. Se o matplotlib estiver instalado, salva os gráficos em PNG.

Uso
---
    python identificacao_zn.py ../dados/manual_20261120_101500.csv
    python identificacao_zn.py ensaio.csv --metodo smith --duty-max 50
    python identificacao_zn.py --sintetico      # demonstração sem a Pi

Dica de ensaio: dê o degrau a partir de um ponto de operação em que o motor
já gira (ex.: 20 % -> 35 %), e não a partir do repouso. Partindo do zero, a
zona morta do motor (duty mínimo para vencer o atrito) distorce K.
"""

import argparse
import csv
import math
import os
import random
import sys
from dataclasses import dataclass, field

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
TS_PROJETO = 0.02      # Ts do controlador em C (controle_c/pid_motor.c)
DUTY_MAX_PROJETO = 50.0  # DUTY_MAX do controlador em C

# Tabela II de Razali et al. (2019): (fator de Kc, fator de Ti, fator de Td)
TABELA_ZN = {
    "P":   (1.0, None, None),
    "PI":  (0.9, 3.33, None),
    "PID": (1.2, 2.0, 0.5),
}


# --------------------------------------------------------------------------
# Estruturas
# --------------------------------------------------------------------------
@dataclass
class Ensaio:
    t: list
    u: list
    y: list
    unidade: str = "RPM"
    origem: str = ""


@dataclass
class Degrau:
    i: int              # Primeira amostra com o duty novo
    fim: int            # Fim do trecho analisado (exclusivo)
    t_degrau: float     # Instante estimado do degrau (incerteza de +-Ts/2)
    u0: float
    u1: float
    y0: float
    yf: float
    avisos: list = field(default_factory=list)

    @property
    def delta_u(self):
        return self.u1 - self.u0

    @property
    def delta_y(self):
        return self.yf - self.y0


@dataclass
class Modelo:
    metodo: str
    K: float
    tau: float
    theta: float
    fit: float = float("nan")
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Leitura do ensaio
# --------------------------------------------------------------------------
def ler_ensaio(caminho):
    """Lê o CSV do painel. Linhas começando com '#' são tratadas como comentário."""
    with open(caminho, newline="", encoding="utf-8") as f:
        linhas = [ln for ln in f if not ln.lstrip().startswith("#")]
    leitor = csv.DictReader(linhas)
    campos = leitor.fieldnames or []
    col_vel = next((c for c in campos if c.startswith("velocidade_")), None)
    if col_vel is None or "tempo_s" not in campos or "duty_pct" not in campos:
        raise ValueError(f"{caminho}: colunas esperadas tempo_s, duty_pct e "
                         f"velocidade_<unidade>; encontradas {campos}")
    t, u, y = [], [], []
    for r in leitor:
        if r.get("modo", "manual") not in ("manual", ""):
            continue    # Só interessa o trecho em malha aberta
        t.append(float(r["tempo_s"]))
        u.append(float(r["duty_pct"]))
        y.append(float(r[col_vel]))
    if len(t) < 10:
        raise ValueError(f"{caminho}: poucas amostras em malha aberta ({len(t)}).")
    return Ensaio(t, u, y, unidade=col_vel[len("velocidade_"):], origem=caminho)


def estatisticas_ts(t):
    """Período de amostragem real: média, desvio-padrão, mínimo e máximo."""
    d = [b - a for a, b in zip(t, t[1:])]
    m = sum(d) / len(d)
    dp = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, len(d) - 1))
    return {"media": m, "desvio": dp, "min": min(d), "max": max(d), "n": len(d)}


def media(v):
    return sum(v) / len(v)


def localizar_degrau(ens, ts, escolha=None):
    """Acha os degraus de duty e escolhe o de maior amplitude (ou o pedido)."""
    u = ens.u
    candidatos = []
    if abs(u[0]) > 1e-9:
        # O painel só começa a gravar quando o modo manual é ligado: a 1ª
        # linha já tem o duty novo e o motor estava parado (duty anterior = 0).
        candidatos.append((0, 0.0))
    candidatos += [(i, u[i - 1]) for i in range(1, len(u)) if abs(u[i] - u[i - 1]) > 1e-9]
    if not candidatos:
        raise ValueError("Nenhum degrau de duty encontrado no ensaio.")

    if escolha is None:
        # Prefere degraus com dados antes deles (y0 medido, motor já girando);
        # o degrau a partir do repouso no início do arquivo só entra se for o único.
        opcoes = [k for k in range(len(candidatos)) if candidatos[k][0] > 0] \
            or list(range(len(candidatos)))
        idx = max(opcoes, key=lambda k: abs(u[candidatos[k][0]] - candidatos[k][1]))
    else:
        if not 1 <= escolha <= len(candidatos):
            raise ValueError(f"--degrau deve estar entre 1 e {len(candidatos)}.")
        idx = escolha - 1
    i, u0 = candidatos[idx]
    fim = candidatos[idx + 1][0] if idx + 1 < len(candidatos) else len(u)
    inicio_anterior = candidatos[idx - 1][0] if idx > 0 else 0

    avisos = []
    # O duty mudou em algum instante entre a amostra i-1 e a i
    t_degrau = ens.t[i] - ts / 2

    if i == 0:
        y0 = 0.0
        avisos.append("O ensaio começa no próprio degrau: assumido y0 = 0 (motor "
                      "parado). Prefira um degrau a partir de um ponto de operação.")
    else:
        janela = ens.y[max(inicio_anterior, i - 20):i]
        y0 = media(janela)
        if len(janela) < 5:
            avisos.append("Menos de 5 amostras antes do degrau: y0 pouco confiável.")

    n_seg = fim - i
    if n_seg < 20:
        raise ValueError(f"Trecho após o degrau muito curto ({n_seg} amostras).")
    n_fim = max(5, n_seg // 5)
    yf = media(ens.y[fim - n_fim:fim])
    # Confere se a resposta realmente estabilizou: compara os dois últimos décimos
    n10 = max(3, n_seg // 10)
    ult = media(ens.y[fim - n10:fim])
    penult = media(ens.y[fim - 2 * n10:fim - n10])
    # Limiar: 2 % de Delta, ou 3 desvios da diferença de duas médias de ruído
    cauda = ens.y[fim - n_fim:fim]
    dp = math.sqrt(sum((v - yf) ** 2 for v in cauda) / max(1, len(cauda) - 1))
    limiar = max(0.02 * abs(yf - y0), 3 * dp * math.sqrt(2 / n10))
    if abs(ult - penult) > limiar:
        avisos.append("A saída ainda variava no fim do trecho: o regime pode não ter "
                      "sido atingido. Mantenha o degrau por mais tempo.")
    return Degrau(i, fim, t_degrau, u0, u[i], y0, yf, avisos), len(candidatos)


# --------------------------------------------------------------------------
# Identificação
# --------------------------------------------------------------------------
def media_movel(v, janela):
    """Média móvel centrada (não desloca o sinal no tempo)."""
    if janela <= 1:
        return list(v)
    m = janela // 2
    out = []
    for k in range(len(v)):
        a, b = max(0, k - m), min(len(v), k + m + 1)
        out.append(sum(v[a:b]) / (b - a))
    return out


def resposta_fopdt(t, t_degrau, y0, K, du, tau, theta):
    """Resposta contínua do modelo de 1ª ordem com atraso a um degrau du."""
    out = []
    for tk in t:
        s = tk - t_degrau - theta
        out.append(y0 + (K * du * (1 - math.exp(-s / tau)) if s > 0 else 0.0))
    return out


def indice_fit(y, yhat):
    """Fit (%) = 100*(1 - ||y - yhat|| / ||y - média(y)||). 100 % = perfeito."""
    m = media(y)
    num = math.sqrt(sum((a - b) ** 2 for a, b in zip(y, yhat)))
    den = math.sqrt(sum((a - m) ** 2 for a in y))
    return 100.0 * (1 - num / den) if den > 0 else float("nan")


def _trecho(ens, dg):
    """Trecho usado no ajuste: um pouco antes do degrau até o fim do segmento."""
    a = max(0, dg.i - 10)
    return ens.t[a:dg.fim], ens.y[a:dg.fim]


def metodo_tangente(ens, dg, janela=5):
    """Razali et al. (2019): reta tangente no ponto de inclinação máxima."""
    t, y = ens.t[dg.i:dg.fim], ens.y[dg.i:dg.fim]
    ys = media_movel(y, janela)
    sinal = 1.0 if dg.delta_y >= 0 else -1.0
    # Inclinação por secante entre amostras vizinhas, no ponto médio do intervalo.
    # A diferença central (k-1, k+1) subestima S logo após o "joelho" da curva.
    melhor, k_s = -math.inf, None
    for k in range(len(ys) - 1):
        d = (ys[k + 1] - ys[k]) / (t[k + 1] - t[k])
        if sinal * d > melhor:
            melhor, k_s = sinal * d, k
    S = sinal * melhor
    if S == 0 or k_s is None:
        raise ValueError("Inclinação máxima nula: a saída não respondeu ao degrau.")
    tS, yS = (t[k_s] + t[k_s + 1]) / 2, (ys[k_s] + ys[k_s + 1]) / 2
    t1 = tS - (yS - dg.y0) / S          # Tangente cruza o nível inicial
    t2 = tS + (dg.yf - yS) / S          # Tangente cruza o nível final
    K = dg.delta_y / dg.delta_u
    mod = Modelo("tangente", K=K, tau=t2 - t1, theta=t1 - dg.t_degrau,
                 extra={"S": S, "tS": tS, "yS": yS, "t1": t1, "t2": t2})
    tt, yy = _trecho(ens, dg)
    mod.fit = indice_fit(yy, resposta_fopdt(tt, dg.t_degrau, dg.y0, K,
                                            dg.delta_u, mod.tau, max(mod.theta, 0)))
    return mod


def _cruzamento(t, ys, nivel, crescente):
    """Primeiro instante em que ys cruza 'nivel' (interpolação linear)."""
    for k in range(1, len(ys)):
        a, b = ys[k - 1], ys[k]
        if (crescente and a < nivel <= b) or (not crescente and a > nivel >= b):
            return t[k - 1] + (nivel - a) * (t[k] - t[k - 1]) / (b - a)
    raise ValueError(f"A saída não cruzou o nível {nivel:.3f}.")


def metodo_smith(ens, dg, janela=5):
    """Dois pontos (28,3 % e 63,2 % de Delta), como comparação."""
    a = max(0, dg.i - 1)
    t, ys = ens.t[a:dg.fim], media_movel(ens.y[a:dg.fim], janela)
    cresc = dg.delta_y >= 0
    t28 = _cruzamento(t, ys, dg.y0 + 0.283 * dg.delta_y, cresc)
    t63 = _cruzamento(t, ys, dg.y0 + 0.632 * dg.delta_y, cresc)
    tau = 1.5 * (t63 - t28)
    K = dg.delta_y / dg.delta_u
    mod = Modelo("smith", K=K, tau=tau, theta=t63 - dg.t_degrau - tau,
                 extra={"t28": t28, "t63": t63})
    tt, yy = _trecho(ens, dg)
    mod.fit = indice_fit(yy, resposta_fopdt(tt, dg.t_degrau, dg.y0, K,
                                            dg.delta_u, tau, max(mod.theta, 0)))
    return mod


# --------------------------------------------------------------------------
# Sintonia e discretização
# --------------------------------------------------------------------------
def sintonia_zn(K, tau, theta):
    """Tabela II de Razali et al. (2019). Retorna Kc, Ti, Td e Kp, Ki, Kd."""
    if theta <= 0:
        raise ValueError("Tempo morto theta <= 0: a Tabela de Ziegler-Nichols "
                         "não se aplica (Kc iria ao infinito).")
    if tau <= 0 or K == 0:
        raise ValueError("Modelo inválido (tau <= 0 ou K = 0).")
    res = {}
    for tipo, (fk, fi, fd) in TABELA_ZN.items():
        Kc = fk / K * tau / theta
        Ti = fi * theta if fi else None
        Td = fd * theta if fd else None
        res[tipo] = {"Kc": Kc, "Ti": Ti, "Td": Td,
                     "kp": Kc, "ki": Kc / Ti if Ti else 0.0, "kd": Kc * Td if Td else 0.0}
    return res


def discretizar_zoh(K, tau, theta, T):
    """ZOH exato de K e^(-theta s)/(tau s + 1), com atraso fracionário.

    theta = d*T + thf, 0 <= thf < T
    G(z) = z^-d (b1 z^-1 + b2 z^-2) / (1 - a z^-1)
    a = e^(-T/tau), b1 = K(1 - e^(-(T-thf)/tau)), b2 = K(e^(-(T-thf)/tau) - a)
    """
    theta = max(theta, 0.0)
    d = int(math.floor(theta / T + 1e-9))
    thf = theta - d * T
    a = math.exp(-T / tau)
    e = math.exp(-(T - thf) / tau)
    return {"a": a, "b1": K * (1 - e), "b2": K * (e - a), "d": d, "thf": thf, "T": T}


class PlantaDiscreta:
    """y[k] = a*y[k-1] + b1*u[k-1-d] + b2*u[k-2-d], em variáveis de desvio."""

    def __init__(self, gz, y0=0.0, u0=0.0):
        self.gz, self.y0, self.u0 = gz, y0, u0
        self.dy = 0.0
        self.hist_u = [0.0] * (gz["d"] + 2)   # Desvios de u: [u[k-1-d], ..., u[k]]

    def passo(self, u):
        """Recebe u[k] e devolve y[k+1]."""
        g = self.gz
        self.hist_u.append(u - self.u0)
        self.hist_u.pop(0)
        self.dy = g["a"] * self.dy + g["b1"] * self.hist_u[-1 - g["d"]] \
            + g["b2"] * self.hist_u[-2 - g["d"]]
        return self.y0 + self.dy


def carregar_pid():
    """PID do controlador em C (cópia em Python, pid_c.py)."""
    sys.path.insert(0, AQUI)
    from pid_c import PIDC
    return PIDC


def simular_malha_fechada(gz, ganhos, y0, u0, setpoint, duracao, duty_max, PID):
    """Malha fechada com o PID do projeto. Parte do equilíbrio (u0, y0)."""
    pid = PID(ganhos["kp"], ganhos["ki"], ganhos["kd"], periodo=gz["T"],
              saida_min=0.0, saida_max=duty_max)
    pid.reiniciar(integral_inicial=u0, erro_inicial=setpoint - y0)
    planta = PlantaDiscreta(gz, y0, u0)
    n = int(round(duracao / gz["T"]))
    t, y, u = [], [], []
    yk = y0
    for k in range(n):
        uk = pid.atualizar(setpoint, yk)
        t.append(k * gz["T"])
        y.append(yk)
        u.append(uk)
        yk = planta.passo(uk)
    return t, y, u


def metricas(t, y, u, y0, setpoint, duty_max):
    """Sobressinal, tempo de acomodação (2 %), erro em regime e saturação."""
    amp = setpoint - y0
    if amp == 0:
        return {}
    sinal = 1 if amp > 0 else -1
    pico = max(y) if sinal > 0 else min(y)
    sobre = max(0.0, 100.0 * (pico - setpoint) * sinal / abs(amp))
    banda = 0.02 * abs(amp)
    ts = None
    for k in range(len(y) - 1, -1, -1):
        if abs(y[k] - setpoint) > banda:
            ts = t[k + 1] if k + 1 < len(t) else None
            break
    else:
        ts = 0.0
    n10 = max(1, len(y) // 10)
    erro_reg = setpoint - media(y[-n10:])
    sat = sum(1 for v in u if v >= duty_max - 1e-9 or v <= 1e-9) / len(u)
    return {"sobressinal_pct": sobre, "t_acomodacao_s": ts,
            "erro_regime": erro_reg, "frac_saturado": sat}


# --------------------------------------------------------------------------
# Dados sintéticos (só para demonstração e testes; NÃO são valores do motor)
# --------------------------------------------------------------------------
def gerar_sintetico(K=2.0, tau=0.30, theta=0.10, ts=0.05, u0=20.0, u1=35.0,
                    t_antes=1.0, t_depois=4.0, ruido=0.0, jitter=0.0, semente=1):
    rnd = random.Random(semente)
    n = int(round((t_antes + t_depois) / ts))
    t, tk = [], 0.0
    for _ in range(n):
        tk += ts + (rnd.uniform(-jitter, jitter) if jitter else 0.0)
        t.append(round(tk, 4))
    i_deg = int(round(t_antes / ts))
    t_degrau = (t[i_deg - 1] + t[i_deg]) / 2
    y0 = K * u0
    u = [u0 if k < i_deg else u1 for k in range(n)]
    y = resposta_fopdt(t, t_degrau, y0, K, u1 - u0, tau, theta)
    if ruido:
        y = [v + rnd.gauss(0.0, ruido) for v in y]
    return Ensaio(t, u, y, unidade="RPM", origem="SINTÉTICO")


# --------------------------------------------------------------------------
# Relatório e gráficos
# --------------------------------------------------------------------------
def _fmt(v, casas=4):
    return "—" if v is None else f"{v:.{casas}g}"


def gerar_relatorio(ens, est_ts, dg, n_deg, modelos, escolhido, zn, gz, sims,
                    duty_max, setpoint):
    un = ens.unidade
    L = []
    L.append("=" * 72)
    L.append("IDENTIFICAÇÃO DA PLANTA (curva de reação) + SINTONIA ZIEGLER-NICHOLS")
    L.append("=" * 72)
    L.append(f"Ensaio: {ens.origem}")
    if ens.origem == "SINTÉTICO":
        L.append("*** DADOS SINTÉTICOS: demonstração, NÃO representam o motor ***")
    L.append(f"Amostras em malha aberta: {len(ens.t)}  |  degraus encontrados: {n_deg}")
    L.append(f"Ts real: média {est_ts['media'] * 1e3:.2f} ms, desvio "
             f"{est_ts['desvio'] * 1e3:.2f} ms, min {est_ts['min'] * 1e3:.2f} ms, "
             f"max {est_ts['max'] * 1e3:.2f} ms")
    L.append("")
    L.append("Degrau analisado")
    L.append(f"  duty: {dg.u0:g} % -> {dg.u1:g} %   (delta = {dg.delta_u:g} %)")
    L.append(f"  t_degrau ~ {dg.t_degrau:.3f} s (incerteza +-Ts/2 = "
             f"+-{est_ts['media'] / 2 * 1e3:.0f} ms, que vai direto para theta)")
    L.append(f"  y0 = {dg.y0:.3f} {un}   yf = {dg.yf:.3f} {un}   "
             f"(Delta = {dg.delta_y:.3f} {un})")
    for a in dg.avisos:
        L.append(f"  AVISO: {a}")
    if dg.delta_y * dg.delta_u < 0:
        L.append("  AVISO: a velocidade caiu quando o duty subiu (K < 0). O sinal do")
        L.append("  encoder está invertido em relação ao sentido do motor: use")
        L.append("  --inverter-sinal aqui e SINAL_ENCODER = -1 no painel.")
    L.append("")
    L.append("Modelo  G(s) = K e^(-theta s) / (tau s + 1)")
    L.append(f"  {'método':<10}{'K [' + un + '/%]':>16}{'tau [s]':>10}{'theta [s]':>11}"
             f"{'fit [%]':>9}")
    for m in modelos:
        marca = "  <- usado" if m is escolhido else ""
        L.append(f"  {m.metodo:<10}{m.K:>16.4g}{m.tau:>10.4g}{m.theta:>11.4g}"
                 f"{m.fit:>9.1f}{marca}")
    if "S" in escolhido.extra:
        L.append(f"  (inclinação máxima S = {escolhido.extra['S']:.4g} {un}/s)")
    melhor = max(modelos, key=lambda m: m.fit)
    if melhor is not escolhido and melhor.fit - escolhido.fit > 2:
        L.append(f"  NOTA: o método '{melhor.metodo}' representa melhor os dados "
                 f"(fit {melhor.fit:.1f} % contra {escolhido.fit:.1f} %). Compare "
                 f"rodando com --metodo {melhor.metodo}.")
    L.append("")
    L.append(f"G(s) = {escolhido.K:.4g} e^(-{max(escolhido.theta, 0):.4g} s) / "
             f"({escolhido.tau:.4g} s + 1)")
    L.append("")
    L.append(f"Discretização ZOH, T = {gz['T'] * 1e3:.0f} ms "
             f"(theta = {gz['d']}*T + {gz['thf'] * 1e3:.1f} ms)")
    L.append(f"  G(z) = z^-{gz['d']} ({gz['b1']:.5g} z^-1 + {gz['b2']:.5g} z^-2) / "
             f"(1 - {gz['a']:.5g} z^-1)")
    L.append(f"  y[k] = {gz['a']:.5g} y[k-1] + {gz['b1']:.5g} u[k-{gz['d'] + 1}] + "
             f"{gz['b2']:.5g} u[k-{gz['d'] + 2}]   (em desvio do ponto de operação)")
    L.append(f"  polo discreto z = {gz['a']:.5g}  (polo contínuo s = {-1 / escolhido.tau:.4g})")
    L.append("")
    if zn is None:
        L.append("Sintonia ZN não calculada (veja o erro acima).")
        return L
    L.append("Ziegler-Nichols, curva de reação (Tabela II de Razali et al., 2019)")
    L.append(f"  {'tipo':<5}{'Kc':>10}{'Ti [s]':>10}{'Td [s]':>10}  |"
             f"{'Kp':>10}{'Ki':>10}{'Kd':>10}   (Kp=Kc, Ki=Kc/Ti, Kd=Kc*Td)")
    for tipo, g in zn.items():
        L.append(f"  {tipo:<5}{g['Kc']:>10.4g}{_fmt(g['Ti']):>10}{_fmt(g['Td']):>10}  |"
                 f"{g['kp']:>10.4g}{g['ki']:>10.4g}{g['kd']:>10.4g}")
    L.append(f"  Unidades: Kc em %/{un}; Ki em %/({un}*s); Kd em %*s/{un}.")
    razao = escolhido.theta / gz["T"]
    if razao < 1:
        L.append("  AVISO: theta < Ts. O tempo morto é menor que um período, então")
        L.append("  Ziegler-Nichols dá ganhos muito altos e a medida de theta fica")
        L.append("  dominada pela incerteza do instante do degrau. Considere")
        L.append("  --atraso-zoh, que soma Ts/2 ao atraso do segurador de ordem zero.")
    elif razao < 4:
        L.append(f"  AVISO: theta/Ts = {razao:.1f}. O atraso que a própria amostragem")
        L.append("  introduz (ZOH, cerca de Ts/2, mais a medição) é comparável ao")
        L.append("  tempo morto. As fórmulas de ZN foram deduzidas para controle")
        L.append("  contínuo e podem levar a malha discreta a oscilar. Confira na")
        L.append("  simulação abaixo e, se for o caso, teste um Ts menor ou --atraso-zoh.")
    L.append("")
    L.append(f"Simulação em malha fechada (PID do controlador em C, saturação 0..{duty_max:g} %,"
             f" setpoint {setpoint:.4g} {un})")
    L.append(f"  {'tipo':<5}{'sobressinal':>13}{'t_acomod 2%':>13}{'erro regime':>13}"
             f"{'% saturado':>12}")
    for tipo, (_, _, _, m) in sims.items():
        ta = m["t_acomodacao_s"]
        ta = "não acomoda" if ta is None else f"{ta:.3g} s"
        L.append(f"  {tipo:<5}{m['sobressinal_pct']:>12.1f}%{ta:>13}"
                 f"{m['erro_regime']:>13.3g}{100 * m['frac_saturado']:>11.0f}%")
    L.append("  Obs.: o modelo é linear em torno do ponto de operação e não inclui")
    L.append("  a zona morta nem o atraso extra da medição de velocidade por média")
    L.append("  no intervalo (cerca de Ts/2). Confirme os ganhos na bancada.")
    return L


def salvar_graficos(ens, dg, modelos, escolhido, sims, setpoint, prefixo):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    un = ens.unidade
    arquivos = []

    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(9, 6.5),
                                   gridspec_kw={"height_ratios": [3, 1]})
    a = max(0, dg.i - 20)
    t, y = ens.t[a:dg.fim], ens.y[a:dg.fim]
    ax1.plot(t, y, ".", ms=3, color="0.5", label="medido")
    for m, cor in zip(modelos, ("C0", "C1")):
        ax1.plot(t, resposta_fopdt(t, dg.t_degrau, dg.y0, m.K, dg.delta_u, m.tau,
                                   max(m.theta, 0)),
                 color=cor, lw=2 if m is escolhido else 1,
                 label=f"modelo {m.metodo} (fit {m.fit:.1f} %)")
    tg = [m for m in modelos if m.metodo == "tangente"]
    if tg:
        e = tg[0].extra
        ax1.plot([e["t1"], e["t2"]], [dg.y0, dg.yf], "k--", lw=1, label="tangente (S máx.)")
    ax1.axhline(dg.y0, color="0.7", lw=0.8)
    ax1.axhline(dg.yf, color="0.7", lw=0.8)
    ax1.axvline(dg.t_degrau, color="0.7", lw=0.8, ls=":")
    ax1.set_ylabel(f"velocidade [{un}]")
    ax1.set_title("Curva de reação e modelo de 1ª ordem com atraso")
    ax1.legend(loc="lower right", fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.step(t, ens.u[a:dg.fim], where="post", color="C2")
    ax2.set_ylabel("duty [%]")
    ax2.set_xlabel("tempo [s]")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    arq = prefixo + "_curva_reacao.png"
    fig.savefig(arq, dpi=150)
    plt.close(fig)
    arquivos.append(arq)

    if sims:
        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(9, 6.5),
                                       gridspec_kw={"height_ratios": [3, 1.3]})
        for tipo, (ts_, ys_, us_, _) in sims.items():
            ax1.plot(ts_, ys_, label=tipo)
            ax2.plot(ts_, us_, label=tipo)
        ax1.axhline(setpoint, color="k", ls="--", lw=0.8, label="setpoint")
        ax1.set_ylabel(f"velocidade [{un}]")
        ax1.set_title("Malha fechada simulada (ganhos Ziegler-Nichols)")
        ax1.legend(fontsize=8)
        ax1.grid(alpha=0.3)
        ax2.set_ylabel("duty [%]")
        ax2.set_xlabel("tempo [s]")
        ax2.grid(alpha=0.3)
        fig.tight_layout()
        arq = prefixo + "_malha_fechada.png"
        fig.savefig(arq, dpi=150)
        plt.close(fig)
        arquivos.append(arq)
    return arquivos


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------
def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", nargs="?", help="CSV do ensaio em malha aberta")
    p.add_argument("--sintetico", action="store_true",
                   help="usa dados sintéticos (demonstração, não é o motor)")
    p.add_argument("--metodo", choices=("tangente", "smith"), default="tangente",
                   help="método cujo modelo vai para a sintonia (padrão: tangente, "
                        "o de Razali et al.)")
    p.add_argument("--degrau", type=int, help="qual degrau usar (1, 2, ...); "
                   "padrão: o de maior amplitude")
    p.add_argument("--janela", type=int, default=5,
                   help="média móvel para reduzir o ruído do encoder (amostras)")
    p.add_argument("--ts", type=float, default=TS_PROJETO,
                   help="Ts usado na discretização e na simulação [s]")
    p.add_argument("--duty-max", type=float, default=DUTY_MAX_PROJETO,
                   help="saturação superior do PID na simulação [%%]")
    p.add_argument("--setpoint", type=float,
                   help="setpoint da simulação (padrão: yf do ensaio)")
    p.add_argument("--duracao", type=float, help="duração da simulação [s]")
    p.add_argument("--ate", type=float,
                   help="ignora as amostras após este tempo [s], para cortar "
                        "perturbações aplicadas depois do regime")
    p.add_argument("--inverter-sinal", action="store_true",
                   help="multiplica a velocidade por -1 (equivale a SINAL_ENCODER = -1)")
    p.add_argument("--atraso-zoh", action="store_true",
                   help="soma Ts/2 a theta na sintonia (atraso do ZOH)")
    p.add_argument("--saida", default=os.path.join(AQUI, "resultados"),
                   help="pasta para o relatório .txt e os gráficos")
    args = p.parse_args(argv)

    if args.sintetico:
        ens = gerar_sintetico(ruido=1.0, jitter=0.002)
    elif args.csv:
        ens = ler_ensaio(args.csv)
    else:
        p.error("informe o CSV do ensaio ou use --sintetico")
    if args.ate is not None:
        n = sum(1 for tk in ens.t if tk <= args.ate)
        ens.t, ens.u, ens.y = ens.t[:n], ens.u[:n], ens.y[:n]
        ens.origem += f" (cortado em t <= {args.ate:g} s)"
    if args.inverter_sinal:
        ens.y = [-v for v in ens.y]
        ens.origem += " (velocidade com sinal invertido)"

    est_ts = estatisticas_ts(ens.t)
    dg, n_deg = localizar_degrau(ens, est_ts["media"], args.degrau)
    if dg.delta_u == 0 or dg.delta_y == 0:
        raise SystemExit("Degrau sem variação na entrada ou na saída.")

    modelos = []
    for f in (metodo_tangente, metodo_smith):
        try:
            modelos.append(f(ens, dg, args.janela))
        except ValueError as exc:
            print(f"Método {f.__name__}: {exc}")
    escolhido = next((m for m in modelos if m.metodo == args.metodo), None)
    if escolhido is None:
        raise SystemExit("Não foi possível identificar o modelo com o método pedido.")

    theta_sint = escolhido.theta + (args.ts / 2 if args.atraso_zoh else 0.0)
    gz = discretizar_zoh(escolhido.K, escolhido.tau, theta_sint, args.ts)
    setpoint = args.setpoint if args.setpoint is not None else dg.yf
    duracao = args.duracao or max(3.0, 10 * (escolhido.tau + max(theta_sint, 0)))

    zn, sims = None, {}
    try:
        zn = sintonia_zn(escolhido.K, escolhido.tau, theta_sint)
    except ValueError as exc:
        print(f"ERRO na sintonia: {exc}")
    if zn:
        PID = carregar_pid()
        for tipo, g in zn.items():
            ts_, ys_, us_ = simular_malha_fechada(gz, g, dg.y0, dg.u0, setpoint,
                                                  duracao, args.duty_max, PID)
            sims[tipo] = (ts_, ys_, us_, metricas(ts_, ys_, us_, dg.y0, setpoint,
                                                  args.duty_max))

    linhas = gerar_relatorio(ens, est_ts, dg, n_deg, modelos, escolhido, zn, gz, sims,
                             args.duty_max, setpoint)
    if args.atraso_zoh:
        linhas.insert(-1, f"(Sintonia com theta + Ts/2 = {theta_sint:.4g} s)")
    texto = "\n".join(linhas)
    print(texto)

    os.makedirs(args.saida, exist_ok=True)
    base = "sintetico" if args.sintetico else os.path.splitext(os.path.basename(args.csv))[0]
    prefixo = os.path.join(args.saida, base)
    with open(prefixo + "_identificacao.txt", "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    figs = salvar_graficos(ens, dg, modelos, escolhido, sims, setpoint, prefixo)
    print(f"\nRelatório salvo em: {prefixo}_identificacao.txt")
    if figs is None:
        print("matplotlib não instalado: gráficos não gerados (pip install matplotlib).")
    else:
        for a in figs:
            print(f"Gráfico salvo em:   {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
