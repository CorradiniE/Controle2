"""
Testes de pid/analise/pid_c.py (cópia em Python do PID de controle_c/pid_motor.c).

    python -m unittest discover -s pid/testes -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analise"))

from pid_c import PIDC  # noqa: E402

T = 0.02


class TestPIDC(unittest.TestCase):
    def test_so_proporcional(self):
        pid = PIDC(2.0, 0.0, 0.0, T, saida_max=100.0)
        self.assertAlmostEqual(pid.atualizar(40.0, 30.0), 20.0)

    def test_integral_euler_retangular(self):
        pid = PIDC(0.0, 10.0, 0.0, T, saida_max=100.0)
        u1 = pid.atualizar(40.0, 30.0)          # I = 10*10*0,02 = 2
        u2 = pid.atualizar(40.0, 30.0)          # I = 4
        self.assertAlmostEqual(u1, 2.0)
        self.assertAlmostEqual(u2, 4.0)

    def test_saturacao_e_anti_windup(self):
        pid = PIDC(1.0, 50.0, 0.0, T, saida_max=50.0)
        pid.reiniciar(integral_inicial=45.0)
        for _ in range(100):                     # erro grande e constante
            u = pid.atualizar(100.0, 0.0)
        self.assertEqual(u, 50.0)
        self.assertAlmostEqual(pid.integral, 45.0)   # não acumulou saturado
        self.assertEqual(PIDC(1, 0, 0, T).atualizar(0.0, 10.0), 0.0)   # limite inferior

    def test_sem_pico_de_derivada_na_partida(self):
        pid = PIDC(0.0, 0.0, 1.0, T, saida_max=100.0)
        pid.reiniciar(integral_inicial=20.0, erro_inicial=10.0)
        self.assertAlmostEqual(pid.atualizar(40.0, 30.0), 20.0)   # erro igual: D = 0

    def test_derivada_filtrada(self):
        """Degrau no erro: a derivada sobe aos poucos (filtro N = 10)."""
        pid = PIDC(0.0, 0.0, 1.0, T, saida_max=1e6)
        alpha = 10 * T / (1 + 10 * T)
        u1 = pid.atualizar(1.0, 0.0)            # erro 0 -> 1
        self.assertAlmostEqual(u1, alpha * (1.0 / T))
        u2 = pid.atualizar(1.0, 0.0)            # erro constante: derivada decai
        self.assertLess(u2, u1)


if __name__ == "__main__":
    unittest.main()
