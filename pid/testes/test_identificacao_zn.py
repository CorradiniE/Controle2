"""
Testes de pid/analise/identificacao_zn.py. Rodam no PC, sem a Pi.

    python -m unittest discover -s pid/testes -v
"""

import math
import os
import sys
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "analise"))

import identificacao_zn as iz  # noqa: E402

T = 0.05


class TestDiscretizacao(unittest.TestCase):
    def test_ganho_dc_igual_a_K(self):
        for theta in (0.0, 0.02, 0.05, 0.13):
            gz = iz.discretizar_zoh(K=2.5, tau=0.4, theta=theta, T=T)
            self.assertAlmostEqual((gz["b1"] + gz["b2"]) / (1 - gz["a"]), 2.5, places=9)

    def test_sem_atraso_fracionario_b2_zero(self):
        gz = iz.discretizar_zoh(K=1.0, tau=0.3, theta=0.10, T=T)
        self.assertEqual((gz["d"], round(gz["thf"], 12)), (2, 0.0))
        gz0 = iz.discretizar_zoh(K=1.0, tau=0.3, theta=0.0, T=T)
        self.assertEqual(gz0["d"], 0)
        self.assertAlmostEqual(gz0["b2"], 0.0, places=12)
        self.assertAlmostEqual(gz0["b1"], 1 - math.exp(-T / 0.3), places=12)

    def test_planta_discreta_bate_com_resposta_continua(self):
        """Nos instantes de amostragem, o ZOH exato reproduz a resposta contínua."""
        K, tau, theta = 2.0, 0.3, 0.12
        gz = iz.discretizar_zoh(K, tau, theta, T)
        planta = iz.PlantaDiscreta(gz)
        y = [0.0] + [planta.passo(1.0) for _ in range(60)]   # degrau unitário em k=0
        tk = [k * T for k in range(61)]
        yc = iz.resposta_fopdt(tk, 0.0, 0.0, K, 1.0, tau, theta)
        for a, b in zip(y, yc):
            self.assertAlmostEqual(a, b, places=9)


class TestSintonia(unittest.TestCase):
    def test_tabela_ii_razali(self):
        zn = iz.sintonia_zn(K=2.0, tau=1.0, theta=0.5)
        self.assertAlmostEqual(zn["P"]["Kc"], 1.0)
        self.assertAlmostEqual(zn["PI"]["Kc"], 0.9)
        self.assertAlmostEqual(zn["PI"]["Ti"], 3.33 * 0.5)
        pid = zn["PID"]
        self.assertAlmostEqual(pid["Kc"], 1.2)
        self.assertAlmostEqual(pid["Ti"], 1.0)
        self.assertAlmostEqual(pid["Td"], 0.25)
        self.assertAlmostEqual(pid["kp"], 1.2)
        self.assertAlmostEqual(pid["ki"], 1.2)
        self.assertAlmostEqual(pid["kd"], 0.3)

    def test_theta_nao_positivo_e_rejeitado(self):
        with self.assertRaises(ValueError):
            iz.sintonia_zn(K=2.0, tau=1.0, theta=0.0)


class TestIdentificacao(unittest.TestCase):
    K, TAU, THETA = 2.0, 0.30, 0.10

    def _identificar(self, ens):
        est = iz.estatisticas_ts(ens.t)
        dg, _ = iz.localizar_degrau(ens, est["media"])
        return dg, iz.metodo_tangente(ens, dg, 1), iz.metodo_smith(ens, dg, 1)

    def test_recupera_modelo_sem_ruido(self):
        ens = iz.gerar_sintetico(self.K, self.TAU, self.THETA)
        dg, tg, sm = self._identificar(ens)
        self.assertAlmostEqual(dg.delta_u, 15.0)
        for m in (tg, sm):
            self.assertAlmostEqual(m.K, self.K, delta=0.01)
            self.assertAlmostEqual(m.theta, self.THETA, delta=T / 2)
        # Dois pontos: exato para um modelo de 1ª ordem com atraso
        self.assertAlmostEqual(sm.tau, self.TAU, delta=0.01)
        self.assertGreater(sm.fit, 99.0)
        # Tangente com amostragem: a inclinação máxima é subestimada, então
        # tau sai maior. O viés esperado fica em torno de 10 a 20 % para T/tau = 1/6.
        self.assertGreater(tg.tau, self.TAU)
        self.assertLess(tg.tau, 1.25 * self.TAU)
        self.assertGreater(tg.fit, 90.0)

    def test_com_ruido_e_jitter(self):
        ens = iz.gerar_sintetico(self.K, self.TAU, self.THETA, ruido=0.5, jitter=0.002)
        est = iz.estatisticas_ts(ens.t)
        dg, _ = iz.localizar_degrau(ens, est["media"])
        sm = iz.metodo_smith(ens, dg, 5)
        self.assertAlmostEqual(sm.K, self.K, delta=0.05)
        self.assertAlmostEqual(sm.tau, self.TAU, delta=2 * T)
        self.assertAlmostEqual(sm.theta, self.THETA, delta=2 * T)


class TestMalhaFechada(unittest.TestCase):
    def test_pid_zn_segue_setpoint(self):
        K, tau, theta = 2.0, 0.3, 0.1
        zn = iz.sintonia_zn(K, tau, theta)
        gz = iz.discretizar_zoh(K, tau, theta, T)
        PID = iz.carregar_pid()
        y0, u0 = K * 20.0, 20.0
        sp = y0 + 20.0
        t, y, u = iz.simular_malha_fechada(gz, zn["PI"], y0, u0, sp, 6.0, 100.0, PID)
        m = iz.metricas(t, y, u, y0, sp, 100.0)
        self.assertLess(abs(m["erro_regime"]), 0.2)
        self.assertTrue(all(0.0 <= v <= 100.0 for v in u))


class TestLeituraCsv(unittest.TestCase):
    def test_formato_do_painel(self):
        """CSV que começa no degrau, como o painel grava ao ligar o modo manual."""
        ens = iz.gerar_sintetico(2.0, 0.3, 0.1, u0=0.0, u1=30.0, t_antes=0.0 + T)
        cab = "tempo_s,modo,setpoint,velocidade_RPM,duty_pct,erro,kp,ki,kd\n"
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "manual_teste.csv")
            with open(caminho, "w", encoding="utf-8", newline="") as f:
                f.write("# ensaio de teste\n" + cab)
                for t, u, y in zip(ens.t[1:], ens.u[1:], ens.y[1:]):
                    f.write(f"{t},manual,,{y:.3f},{u},,0.0,0.0,0.0\n")
            lido = iz.ler_ensaio(caminho)
        self.assertEqual(lido.unidade, "RPM")
        est = iz.estatisticas_ts(lido.t)
        dg, n = iz.localizar_degrau(lido, est["media"])
        self.assertEqual((n, dg.i, dg.u0, dg.u1, dg.y0), (1, 0, 0.0, 30.0, 0.0))
        self.assertTrue(dg.avisos)


if __name__ == "__main__":
    unittest.main()
