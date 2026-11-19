#!/usr/bin/env python3
"""
girar.py - Teste minimo da ponte H.
Gira o motor 4 s em um sentido, para, gira 4 s no outro sentido e para.
Nao depende de nenhum outro arquivo do projeto.
"""

import time

import lgpio

ENA, IN1, IN2 = 18, 23, 24   # Pinos fisicos 12, 16 e 18
DUTY = 50                    # % - seguro para o motor de 6 V com fonte de ate 12 V
FREQ = 1000                  # Hz

h = lgpio.gpiochip_open(0)
try:
    for pino in (ENA, IN1, IN2):
        lgpio.gpio_claim_output(h, pino, 0)

    print(f"Sentido 1, duty {DUTY}% por 4 s...")
    lgpio.gpio_write(h, IN1, 1)
    lgpio.gpio_write(h, IN2, 0)
    lgpio.tx_pwm(h, ENA, FREQ, DUTY)
    time.sleep(4)

    print("Parando 1 s...")
    lgpio.tx_pwm(h, ENA, FREQ, 0)
    lgpio.gpio_write(h, IN1, 0)
    time.sleep(1)

    print(f"Sentido 2, duty {DUTY}% por 4 s...")
    lgpio.gpio_write(h, IN2, 1)
    lgpio.tx_pwm(h, ENA, FREQ, DUTY)
    time.sleep(4)

finally:
    # Sempre deixa o motor parado, mesmo se der erro ou Ctrl+C
    lgpio.tx_pwm(h, ENA, FREQ, 0)
    lgpio.gpio_write(h, IN1, 0)
    lgpio.gpio_write(h, IN2, 0)
    lgpio.gpiochip_close(h)
    print("Motor parado.")
