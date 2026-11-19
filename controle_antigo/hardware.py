#!/usr/bin/env python3
"""
hardware.py - Acesso ao hardware do projeto.

Contem:
  - Motor:   controle do L298N (sentido por IN1/IN2 e velocidade por PWM no ENA)
  - Encoder: leitura do encoder incremental em quadratura (contagem 4x)

Mapa de pinos (numeracao BCM / GPIO):
  ENA  -> GPIO 18 (pino fisico 12)
  IN1  -> GPIO 23 (pino fisico 16)
  IN2  -> GPIO 24 (pino fisico 18)
  C1/A -> GPIO 17 (pino fisico 11) - fio amarelo
  C2/B -> GPIO 27 (pino fisico 13) - fio verde
"""

import threading
import time

import lgpio

CHIP = 0            # No Raspberry Pi 4, o conector de 40 pinos esta no gpiochip0

PINO_ENA = 18
PINO_IN1 = 23
PINO_IN2 = 24
PINO_ENC_A = 17
PINO_ENC_B = 27

FREQ_PWM = 1000     # Frequencia do PWM no ENA, em Hz

# LIMITE DE SEGURANCA do duty cycle, em %.
# O motor e de 6 V. Comece com 50 e ajuste com o multimetro
# conforme o procedimento do guia. Nenhum comando passa deste valor.
DUTY_MAX = 50

# CALIBRACAO DO ENCODER - unico lugar onde estes valores ficam.
# Contagens 4x por volta do eixo de SAIDA, medidas com calibrar_encoder.py
# em 2026-11-19 (media de 10 voltas; valor preliminar, a confirmar girando
# o eixo a mao com contar_pulsos.py).
CONTAGENS_POR_VOLTA = 3421

# Sinal da contagem: no sentido +1 do motor a contagem DIMINUI (ensaio de
# 2026-11-19), entao multiplicamos por -1 para a velocidade sair positiva.
SINAL_ENCODER = -1


def contagens_para_rpm(contagens_por_s):
    """Converte a taxa do encoder (contagens/s) em RPM do eixo de saida."""
    return SINAL_ENCODER * contagens_por_s * 60.0 / CONTAGENS_POR_VOLTA


class Motor:
    """Controla o motor pela ponte A do L298N."""

    def __init__(self, h, duty_max=DUTY_MAX):
        self.h = h
        self.duty_max = duty_max
        self.duty = 0.0
        self.sentido = 0          # +1, -1 ou 0 (parado)
        for pino in (PINO_ENA, PINO_IN1, PINO_IN2):
            lgpio.gpio_claim_output(h, pino, 0)   # Comeca tudo em nivel baixo

    def definir_sentido(self, sentido):
        """sentido = +1 (IN1=1, IN2=0) ou -1 (IN1=0, IN2=1)."""
        if sentido not in (1, -1):
            raise ValueError("sentido deve ser +1 ou -1")
        if self.sentido != 0 and sentido != self.sentido:
            # Nunca inverter com o motor girando: para e espera desacelerar
            self.parar()
            time.sleep(0.5)
        lgpio.gpio_write(self.h, PINO_IN1, 1 if sentido == 1 else 0)
        lgpio.gpio_write(self.h, PINO_IN2, 0 if sentido == 1 else 1)
        self.sentido = sentido

    def definir_duty(self, duty):
        """Aplica o duty cycle (%) no ENA, limitado entre 0 e duty_max."""
        if self.sentido == 0:
            raise RuntimeError("Defina o sentido antes de aplicar o duty")
        duty = max(0.0, min(float(duty), self.duty_max))
        lgpio.tx_pwm(self.h, PINO_ENA, FREQ_PWM, duty)
        self.duty = duty
        return duty

    def parar(self):
        """Zera o PWM e desliga as duas entradas (motor livre)."""
        lgpio.tx_pwm(self.h, PINO_ENA, FREQ_PWM, 0)
        lgpio.gpio_write(self.h, PINO_IN1, 0)
        lgpio.gpio_write(self.h, PINO_IN2, 0)
        self.duty = 0.0
        self.sentido = 0

    def fechar(self):
        """Encerramento seguro: para o motor e libera os pinos."""
        self.parar()
        for pino in (PINO_ENA, PINO_IN1, PINO_IN2):
            lgpio.gpio_free(self.h, pino)


class Encoder:
    """Le o encoder em quadratura, contando as bordas dos dois canais (4x)."""

    # Indice = estado_anterior * 4 + estado_novo, com estado = (A << 1) | B
    TABELA = [0, -1, +1, 0,
              +1, 0, 0, -1,
              -1, 0, 0, +1,
              0, +1, -1, 0]

    def __init__(self, h):
        self.h = h
        self._trava = threading.Lock()
        self._posicao = 0
        self._erros = 0
        self._nivel = {}
        self._callbacks = []
        for pino in (PINO_ENC_A, PINO_ENC_B):
            lgpio.gpio_claim_alert(h, pino, lgpio.BOTH_EDGES, lgpio.SET_PULL_UP)
            self._nivel[pino] = lgpio.gpio_read(h, pino)
            self._callbacks.append(
                lgpio.callback(h, pino, lgpio.BOTH_EDGES, self._ao_mudar))

    def _ao_mudar(self, chip, gpio, nivel, tick):
        """Chamada pelo lgpio a cada borda em A ou B."""
        if nivel not in (0, 1):       # 2 = aviso de watchdog; ignorar
            return
        with self._trava:
            anterior = (self._nivel[PINO_ENC_A] << 1) | self._nivel[PINO_ENC_B]
            self._nivel[gpio] = nivel
            novo = (self._nivel[PINO_ENC_A] << 1) | self._nivel[PINO_ENC_B]
            if anterior == novo:
                return
            passo = self.TABELA[anterior * 4 + novo]
            if passo == 0:
                self._erros += 1      # Transicao invalida: ruido ou borda perdida
            self._posicao += passo

    def contagem(self):
        """Posicao acumulada (contagens 4x, com sinal)."""
        with self._trava:
            return self._posicao

    def erros(self):
        with self._trava:
            return self._erros

    def fechar(self):
        for cb in self._callbacks:
            cb.cancel()
        for pino in (PINO_ENC_A, PINO_ENC_B):
            lgpio.gpio_free(self.h, pino)
