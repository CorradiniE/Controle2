#!/usr/bin/env python3
"""
calibrar_encoder.py - Etapa B: mede as contagens 4x por volta do eixo de saida.

O motor gira devagar e voce aperta Enter cada vez que a marca de fita
passa pelo ponto de referencia. O script registra a contagem do encoder
em cada Enter e calcula a media de contagens por volta.
"""

import statistics
import time

import lgpio

from hardware import CHIP, Encoder, Motor

DUTY_CALIBRACAO = 30   # Ajuste: menor duty em que o motor gira devagar e sem engasgar
VOLTAS = 10            # Numero de voltas medidas


def main():
    h = lgpio.gpiochip_open(CHIP)
    motor = Motor(h)
    enc = Encoder(h)
    try:
        motor.definir_sentido(+1)
        motor.definir_duty(DUTY_CALIBRACAO)
        print(f"Motor girando a {DUTY_CALIBRACAO}%. Aguardando estabilizar...")
        time.sleep(2.0)

        print("\nAperte Enter quando a fita passar pela referencia.")
        print(f"Sao {VOLTAS + 1} Enter: o primeiro marca o inicio.\n")
        marcas = []
        for i in range(VOLTAS + 1):
            input(f"  Enter {i + 1}/{VOLTAS + 1}")
            marcas.append((enc.contagem(), time.monotonic()))
    except KeyboardInterrupt:
        print("\nCalibracao interrompida.")
        marcas = []
    finally:
        motor.fechar()
        enc.fechar()
        lgpio.gpiochip_close(h)

    if len(marcas) < 3:
        return

    por_volta = [abs(marcas[i + 1][0] - marcas[i][0]) for i in range(len(marcas) - 1)]
    total = abs(marcas[-1][0] - marcas[0][0])
    tempo = marcas[-1][1] - marcas[0][1]
    voltas = len(por_volta)
    media = total / voltas

    print("\nContagens em cada volta:", por_volta)
    print(f"Media (total / voltas)  : {media:.1f} contagens por volta (4x)")
    print(f"Menor / maior volta     : {min(por_volta)} / {max(por_volta)}")
    print(f"Desvio padrao           : {statistics.stdev(por_volta):.1f}")
    print(f"Rotacao durante o teste : {voltas * 60 / tempo:.1f} RPM")
    print(f"Pulsos por volta, 1 canal (1x): {media / 4:.1f}")
    print(f"\nValor a usar em hardware.py: CONTAGENS_POR_VOLTA = {round(media)}")


if __name__ == "__main__":
    main()
