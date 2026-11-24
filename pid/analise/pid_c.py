"""
pid_c.py - Cópia, em Python, do PID de controle_c/pid_motor.c, para simular no PC.

Mesma lei de controle do C (Ts = 20 ms):
  e[k]  = setpoint - medida
  d_f   = d_f + alpha*((e[k] - e[k-1])/T - d_f),   alpha = N*T/(1 + N*T)
          (derivada do ERRO, com filtro passa-baixa de 1ª ordem, N = 10)
  I_new = I + Ki*e[k]*T                             (Euler retangular)
  u_raw = Kp*e[k] + I_new + Kd*d_f
  u     = u_raw saturado em [saida_min, saida_max]
  I     = I_new só se u não saturou                 (anti-windup condicional)

Se mudar a lei no pid_motor.c, mude aqui também. Os testes em
pid/testes/test_pid_c.py conferem saturação, anti-windup e derivada.
"""


class PIDC:
    def __init__(self, kp, ki, kd, periodo, saida_min=0.0, saida_max=50.0, n_filtro=10.0):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.T = periodo
        self.saida_min, self.saida_max = saida_min, saida_max
        self.alpha = n_filtro * periodo / (1.0 + n_filtro * periodo)
        self.reiniciar()

    def reiniciar(self, integral_inicial=0.0, erro_inicial=0.0):
        """Como no C ao entrar no modo PID: integral = duty atual (sem tranco) e
        erro anterior = erro atual (sem pico na derivada)."""
        self.integral = integral_inicial
        self.e_prev = erro_inicial
        self.d_f = 0.0

    def atualizar(self, setpoint, medida):
        e = setpoint - medida
        self.d_f += self.alpha * ((e - self.e_prev) / self.T - self.d_f)
        i_novo = self.integral + self.ki * e * self.T
        u_raw = self.kp * e + i_novo + self.kd * self.d_f
        u = min(max(u_raw, self.saida_min), self.saida_max)
        if u == u_raw:
            self.integral = i_novo
        self.e_prev = e
        return u
