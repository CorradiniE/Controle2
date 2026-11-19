#!/usr/bin/env python3
"""
contar_pulsos.py - Leitura do encoder sem o motor alimentado.

Conta as bordas dos canais A (GPIO 17) e B (GPIO 27) do encoder enquanto
o eixo e girado a mao. Util para conferir se os dois canais funcionam.
(Para medir as contagens por volta, use calibrar_encoder.py.)

O motor NAO deve estar alimentado neste teste.
Encerrar com Ctrl+C.
"""

import threading
import time

import lgpio

CHIP = 0        # No Raspberry Pi 4, os pinos do conector ficam no gpiochip0
PINO_A = 17     # Pino fisico 11 - fio amarelo (C1)
PINO_B = 27     # Pino fisico 13 - fio verde (C2)

# Tabela de decodificacao em quadratura.
# Indice = (estado_anterior * 4) + estado_novo, onde estado = (A << 1) | B.
#  +1 = um passo em um sentido, -1 = um passo no outro,
#   0 = sem mudanca ou transicao invalida (os dois canais mudaram juntos).
TABELA = [0, -1, +1, 0,
          +1, 0, 0, -1,
          -1, 0, 0, +1,
          0, +1, -1, 0]

trava = threading.Lock()
posicao = 0                       # Contagem 4x com sinal (indica o sentido)
bordas = {PINO_A: 0, PINO_B: 0}   # Bordas brutas de cada canal
erros = 0                         # Transicoes invalidas (ruido ou pulso perdido)
nivel = {PINO_A: 0, PINO_B: 0}    # Ultimo nivel conhecido de cada canal


def ao_mudar(chip, gpio, novo_nivel, tick):
    """Chamada pelo lgpio a cada borda (subida ou descida) em A ou B."""
    global posicao, erros
    if novo_nivel not in (0, 1):  # 2 = aviso de watchdog do lgpio; ignorar
        return
    with trava:
        anterior = (nivel[PINO_A] << 1) | nivel[PINO_B]
        nivel[gpio] = novo_nivel
        novo = (nivel[PINO_A] << 1) | nivel[PINO_B]
        if anterior == novo:
            return
        passo = TABELA[anterior * 4 + novo]
        if passo == 0:
            erros += 1
        posicao += passo
        bordas[gpio] += 1


def main():
    h = lgpio.gpiochip_open(CHIP)
    callbacks = []
    try:
        for pino in (PINO_A, PINO_B):
            # Entrada com deteccao das duas bordas e pull-up interno
            lgpio.gpio_claim_alert(h, pino, lgpio.BOTH_EDGES, lgpio.SET_PULL_UP)
            nivel[pino] = lgpio.gpio_read(h, pino)
            callbacks.append(lgpio.callback(h, pino, lgpio.BOTH_EDGES, ao_mudar))

        print("Gire o eixo a mao. Ctrl+C para encerrar.\n")
        print(f"{'posicao (4x)':>14} {'bordas A':>10} {'bordas B':>10} {'erros':>7}")
        while True:
            with trava:
                linha = (f"{posicao:>14} {bordas[PINO_A]:>10} "
                         f"{bordas[PINO_B]:>10} {erros:>7}")
            print(linha, end="\r", flush=True)
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n\nResultado final:")
        print(f"  posicao (4x) = {posicao}")
        print(f"  bordas A = {bordas[PINO_A]} | bordas B = {bordas[PINO_B]}")
        print(f"  erros = {erros}")

    finally:
        # Encerramento seguro: cancela callbacks e libera os GPIO
        for cb in callbacks:
            cb.cancel()
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    main()
