#!/usr/bin/env python3
"""
teste_motor.py - Etapa A: teste da ponte H em malha aberta.

Comandos:
  f        sentido direto        r   sentido reverso
  0 a 100  duty cycle (%)        s   parar
  m        medir de novo         q   sair
"""

import time

import lgpio

from hardware import CHIP, DUTY_MAX, Encoder, Motor

# Preencher depois de rodar calibrar_encoder.py (None = ainda desconhecido)
CONTAGENS_POR_VOLTA = None


def medir(enc, segundos=2.0):
    """Mede a taxa de contagens por segundo em uma janela de tempo."""
    c0, t0 = enc.contagem(), time.monotonic()
    time.sleep(segundos)
    c1, t1 = enc.contagem(), time.monotonic()
    return (c1 - c0) / (t1 - t0)


def mostrar(enc, motor):
    taxa = medir(enc)
    texto = f"duty {motor.duty:5.1f}% | {taxa:9.1f} contagens/s | erros {enc.erros()}"
    if CONTAGENS_POR_VOLTA:
        rpm = taxa * 60 / CONTAGENS_POR_VOLTA
        texto += f" | {rpm:6.1f} RPM"
    print(texto)


def main():
    h = lgpio.gpiochip_open(CHIP)
    motor = Motor(h)
    enc = Encoder(h)
    print(__doc__)
    print(f"Limite de seguranca atual: DUTY_MAX = {DUTY_MAX}%\n")
    try:
        while True:
            cmd = input("> ").strip().lower()
            if cmd == "q":
                break
            elif cmd == "f":
                motor.definir_sentido(+1)
                print("Sentido: direto. Agora informe o duty.")
            elif cmd == "r":
                motor.definir_sentido(-1)
                print("Sentido: reverso. Agora informe o duty.")
            elif cmd == "s":
                motor.parar()
                print("Motor parado.")
            elif cmd == "m":
                mostrar(enc, motor)
            elif cmd.replace(".", "", 1).isdigit():
                if motor.sentido == 0:
                    print("Escolha o sentido antes (f ou r).")
                    continue
                aplicado = motor.definir_duty(float(cmd))
                if aplicado < float(cmd):
                    print(f"Limitado a DUTY_MAX = {aplicado:.0f}%")
                time.sleep(1.0)          # Espera a velocidade estabilizar
                mostrar(enc, motor)
            else:
                print("Comando invalido.")
    except KeyboardInterrupt:
        print()
    finally:
        motor.fechar()                   # Sempre para o motor ao sair
        enc.fechar()
        lgpio.gpiochip_close(h)
        print("Motor parado e GPIO liberados.")


if __name__ == "__main__":
    main()
