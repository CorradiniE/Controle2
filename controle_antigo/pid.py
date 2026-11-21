#!/usr/bin/env python3
"""
pid.py - Controlador PID discreto (forma posicional).

  e[k] = setpoint - medida
  P[k] = Kp * e[k]
  I[k] = I[k-1] + Ki * e[k] * T                (com anti-windup)
  D[k] = -Kd * (y[k] - y[k-1]) / T             (derivada da medida, filtrada)
  u[k] = P[k] + I[k] + D[k], saturado entre saida_min e saida_max

Relacao com a forma usada nos artigos (Kc, Ti, Td):
  Kp = Kc,   Ki = Kc / Ti,   Kd = Kc * Td

Unidades neste projeto: erro em RPM, saida em % de duty cycle.
"""


class PID:
    def __init__(self, kp, ki, kd, periodo, saida_min=0.0, saida_max=100.0,
                 alfa_d=0.7):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.T = periodo              # Periodo de amostragem, em segundos
        self.saida_min = saida_min
        self.saida_max = saida_max
        self.alfa_d = alfa_d          # Filtro da derivada (0 = sem filtro)
        self.reiniciar()

    def reiniciar(self, integral_inicial=0.0):
        """Zera a memoria do controlador.

        integral_inicial permite partir do duty que ja estava sendo aplicado,
        evitando um tranco ao passar da malha aberta para o PID.
        """
        self.integral = min(max(integral_inicial, self.saida_min), self.saida_max)
        self.medida_anterior = None
        self.d_filtrado = 0.0
        self.ultimo_p = 0.0           # Ultimos termos calculados (para o registro)
        self.ultimo_d = 0.0

    def atualizar(self, setpoint, medida):
        """Calcula a nova saida. Deve ser chamado uma vez a cada periodo T."""
        erro = setpoint - medida

        # Termo proporcional
        p = self.kp * erro

        # Termo derivativo: calculado sobre a medida (nao sobre o erro),
        # para nao gerar um pico quando o setpoint muda de repente.
        if self.medida_anterior is None:
            d_bruto = 0.0
        else:
            d_bruto = -self.kd * (medida - self.medida_anterior) / self.T
        self.medida_anterior = medida
        self.d_filtrado = self.alfa_d * self.d_filtrado + (1 - self.alfa_d) * d_bruto
        d = self.d_filtrado

        # Termo integral com anti-windup por integracao condicional:
        # se a saida ja esta saturada e o erro empurra para alem do limite,
        # a integral nao acumula.
        integral_nova = self.integral + self.ki * erro * self.T
        u = p + integral_nova + d
        satura_acima = u > self.saida_max and erro > 0
        satura_abaixo = u < self.saida_min and erro < 0
        if not (satura_acima or satura_abaixo):
            self.integral = integral_nova

        # Saida final, saturada no intervalo permitido
        self.ultimo_p, self.ultimo_d = p, d
        u = p + self.integral + d
        return min(max(u, self.saida_min), self.saida_max)
