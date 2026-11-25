/* pid_motor.c - controle PID de velocidade do motor DC (versao em C)
 *
 * Base: arquivo "Codigo PID" da branch Codigo-Controlador-C (FSLouredo), escrito
 * para a pigpio. A pigpio nao existe no Raspberry Pi OS atual (Debian 13 trixie),
 * entao o acesso ao hardware foi trocado pela lgpio, a mesma biblioteca usada
 * pelo painel em Python. A logica de controle (decodificacao do encoder, PID com
 * derivada filtrada e anti-windup, laco com periodo fixo) e a do original.
 * Ajustes para o nosso hardware estao marcados com "AJUSTE:".
 *
 * Instalar:  sudo apt install -y liblgpio-dev            (precisa de internet)
 * Compilar:  gcc -O2 -Wall -o pid_motor pid_motor.c -llgpio
 *
 * Dois jeitos de usar:
 *   ./pid_motor 40 1.5 7.5 0   liga o PID direto (setpoint kp ki kd). Ctrl+C para.
 *   ./pid_motor                fica parado esperando comandos do painel web
 *                              (python3 painel_c.py, em outro terminal).
 *
 * Painel (painel_c.py) <-> este programa, por UDP local (127.0.0.1):
 *   comandos   -> porta 5006, texto: "parar" | "manual <duty>" |
 *                 "pid <setpoint> <kp> <ki> <kd>" | "ping"
 *   telemetria <- porta 5005, uma linha por amostra:
 *                 t,modo,setpoint,rpm,duty,erro,kp,ki,kd,aviso,arquivo
 * Se o painel parar de mandar sinal por mais de 2 s, o motor para (seguranca).
 *
 * Nao rodar junto com o painel.py: so um programa pode usar os GPIO por vez.
 */
#include <lgpio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sched.h>
#include <time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define CHIP      0           /* gpiochip0 = conector de 40 pinos da Pi 4 */
#define PWM_PIN   18          /* ENA do L298N (pino fisico 12) */
#define IN1       23
#define IN2       24
#define ENC_A     17
#define ENC_B     27
/* AJUSTE: contagens 4x por volta do eixo de saida, medidas com calibrar_encoder.py
 * (branch Projeto_Controle_Python). O original tinha 374*4 = 1496. */
#define PPR       3421
/* AJUSTE: no sentido IN1=1/IN2=0 a contagem diminui (ensaio de 2026-11-19).
 * Sem este -1 o RPM sai negativo e o PID acelera ate o maximo. */
#define SINAL_ENCODER (-1)
/* AJUSTE: limite de seguranca do duty (motor de 6 V com fonte de ate 12 V),
 * igual ao DUTY_MAX da versao em Python. O original ia ate 100 %. */
#define DUTY_MAX  50.0
#define TS        0.02        /* periodo de amostragem [s] */
#define PWM_FREQ  1000        /* frequencia do PWM [Hz] */
#define N_FILTRO  10.0        /* constante do filtro da derivada */

#define PORTA_TELEMETRIA 5005 /* este programa -> painel */
#define PORTA_COMANDOS   5006 /* painel -> este programa */
#define TIMEOUT_PAINEL   2.0  /* s sem sinal do painel = para o motor */

enum { PARADO, MANUAL, PID };
static const char *NOME_MODO[] = { "parado", "manual", "pid" };

/* AJUSTE: ganhos iniciais = PI validado na bancada (Kp 1,5 / Ki 7,5 / Kd 0).
 * Os do original (2 / 40 / 0,1) oscilam no modelo do nosso motor. */
static double setpoint = 40.0, kp = 1.5, ki = 7.5, kd = 0.0;
static int modo = PARADO;
static double duty_manual = 0.0;
static double I = 0.0, e_prev = 0.0, d_f = 0.0;   /* memoria do PID */
static int aviso = 0;          /* 1 = protecao de velocidade negativa atuou */

static FILE *arq = NULL;
static char nome_arq[200] = "";

static volatile long count = 0;
static volatile int levA = 0, levB = 0;
static volatile sig_atomic_t running = 1;

static void on_sigint(int sig) { (void)sig; running = 0; }

/* decodificacao em quadratura x4: a lgpio entrega as bordas de A ou B em lotes */
static void enc_cb(int num_alerts, lgGpioAlert_p alerts, void *userdata)
{
    (void)userdata;
    for (int i = 0; i < num_alerts; i++) {
        int gpio = alerts[i].report.gpio;
        int level = alerts[i].report.level;
        if (level > 1) continue;                 /* 2 = aviso de watchdog */
        if (gpio == ENC_A) {
            levA = level;
            __atomic_add_fetch(&count, (levA != levB) ? 1 : -1, __ATOMIC_RELAXED);
        } else if (gpio == ENC_B) {
            levB = level;
            __atomic_add_fetch(&count, (levA == levB) ? 1 : -1, __ATOMIC_RELAXED);
        }
    }
}

/* ---------- CSV: um arquivo por ensaio (por modo e por conjunto de ganhos) ---------- */
static void fechar_csv(void)
{
    if (arq) fclose(arq);
    arq = NULL;
    nome_arq[0] = '\0';
}

static void abrir_csv(double duty_ini, double rpm_ini)
{
    fechar_csv();
    char data[32], base[120];
    time_t agora = time(NULL);
    strftime(data, sizeof data, "%Y%m%d_%H%M%S", localtime(&agora));
    if (modo == PID)
        snprintf(base, sizeof base, "pidc_%s_kp%g_ki%g_kd%g.csv", data, kp, ki, kd);
    else
        snprintf(base, sizeof base, "manualc_%s.csv", data);
    /* Grava em ../pid/dados/ (repositorio) se existir; senao, na pasta atual */
    snprintf(nome_arq, sizeof nome_arq, "../pid/dados/%s", base);
    arq = fopen(nome_arq, "w");
    if (!arq) {
        snprintf(nome_arq, sizeof nome_arq, "%s", base);
        arq = fopen(nome_arq, "w");
    }
    if (!arq) { nome_arq[0] = '\0'; return; }
    fprintf(arq, "# Ensaio %s em C (controle_c/pid_motor.c, lgpio) - %s\n", NOME_MODO[modo], data);
    fprintf(arq, "# Ts nominal = %g s | DUTY_MAX = %g %% | CONTAGENS_POR_VOLTA = %d | "
                 "SINAL_ENCODER = %d\n", TS, DUTY_MAX, PPR, SINAL_ENCODER);
    if (modo == PID)
        fprintf(arq, "# Ganhos: Kp = %g | Ki = %g | Kd = %g (derivada do erro, filtro N = %g) | "
                     "setpoint inicial = %g RPM | duty no inicio = %.1f %% | velocidade no "
                     "inicio = %.1f RPM\n", kp, ki, kd, N_FILTRO, setpoint, duty_ini, rpm_ini);
    fprintf(arq, "# Condicoes/observacoes: (anotar aqui)\n");
    fprintf(arq, "tempo_s,modo,setpoint,velocidade_RPM,duty_pct,erro,kp,ki,kd,dt_ms\n");
    printf("Gravando em %s\n", nome_arq);
}

/* ---------- Comandos (do painel ou da linha de comando) ---------- */
static void tratar_comando(const char *cmd, double duty_atual, double rpm)
{
    double a, b, c, d;
    if (strncmp(cmd, "ping", 4) == 0) {
        return;
    } else if (strncmp(cmd, "parar", 5) == 0) {
        modo = PARADO;
        fechar_csv();
    } else if (sscanf(cmd, "manual %lf", &a) == 1) {
        if (a < 0) a = 0;
        if (a > DUTY_MAX) a = DUTY_MAX;
        duty_manual = a;
        if (modo != MANUAL) {
            modo = MANUAL;
            abrir_csv(duty_atual, rpm);
        }
    } else if (sscanf(cmd, "pid %lf %lf %lf %lf", &a, &b, &c, &d) == 4) {
        if (a <= 0 || b < 0 || c < 0 || d < 0) return;
        int ganhos_mudaram = (b != kp || c != ki || d != kd);
        setpoint = a; kp = b; ki = c; kd = d;
        if (modo != PID) {
            /* Partida sem tranco: a integral comeca no duty que ja estava aplicado */
            I = duty_atual;
            e_prev = setpoint - rpm;
            d_f = 0.0;
            aviso = 0;
            modo = PID;
            abrir_csv(duty_atual, rpm);
        } else if (ganhos_mudaram) {
            abrir_csv(duty_atual, rpm);   /* ganhos novos = arquivo novo */
        }
        /* So o setpoint mudou: segue no mesmo arquivo (degrau na coluna setpoint) */
    }
}

/* Para o motor e libera os pinos (chamado em qualquer saida normal) */
static void encerrar(int h)
{
    lgTxPwm(h, PWM_PIN, PWM_FREQ, 0, 0, 0);       /* duty 0 */
    lgGpioWrite(h, IN1, 0);
    lgGpioWrite(h, IN2, 0);
    lgGpioFree(h, ENC_A);
    lgGpioFree(h, ENC_B);
    lgGpioFree(h, PWM_PIN);
    lgGpioFree(h, IN1);
    lgGpioFree(h, IN2);
    lgGpiochipClose(h);
}

static double segundos(struct timespec a, struct timespec b)
{
    return (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) * 1e-9;
}

int main(int argc, char **argv)
{
    int pid_direto = 0;
    if (argc == 5) {
        pid_direto = 1;
    } else if (argc != 1) {
        fprintf(stderr, "Uso: %s [setpoint kp ki kd]\n", argv[0]);
        return 1;
    }

    int h = lgGpiochipOpen(CHIP);
    if (h < 0) {
        fprintf(stderr, "Falha ao abrir o gpiochip%d (%s)\n", CHIP, lguErrorText(h));
        return 1;
    }
    signal(SIGINT, on_sigint);
    signal(SIGTERM, on_sigint);

    /* Prioridade de tempo real: so funciona com sudo; sem ela o laco roda normal */
    struct sched_param sp = { .sched_priority = 80 };
    if (sched_setscheduler(0, SCHED_FIFO, &sp) != 0)
        printf("Aviso: sem prioridade de tempo real (rode com sudo para ativar).\n");

    /* Saidas comecam em nivel baixo: motor parado */
    if (lgGpioClaimOutput(h, 0, PWM_PIN, 0) < 0 || lgGpioClaimOutput(h, 0, IN1, 0) < 0 ||
        lgGpioClaimOutput(h, 0, IN2, 0) < 0) {
        fprintf(stderr, "GPIO ocupado: feche o painel.py ou outro script.\n");
        lgGpiochipClose(h);
        return 1;
    }
    /* AJUSTE: parado = IN1 e IN2 em 0 (ponte H desligada, motor livre), como na versao
     * em Python. O sentido (+1) so e ligado ao entrar em manual/PID (no laco). */
    lgGpioWrite(h, IN1, 0);
    lgGpioWrite(h, IN2, 0);

    /* Encoder: entrada com pull-up, alerta nas duas bordas */
    lgGpioClaimAlert(h, LG_SET_PULL_UP, LG_BOTH_EDGES, ENC_A, -1);
    lgGpioClaimAlert(h, LG_SET_PULL_UP, LG_BOTH_EDGES, ENC_B, -1);
    levA = lgGpioRead(h, ENC_A);
    levB = lgGpioRead(h, ENC_B);
    lgGpioSetAlertsFunc(h, ENC_A, enc_cb, NULL);
    lgGpioSetAlertsFunc(h, ENC_B, enc_cb, NULL);

    /* UDP local: recebe comandos (nao bloqueia) e envia telemetria */
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in end_cmd = { 0 }, end_tel = { 0 };
    end_cmd.sin_family = AF_INET;
    end_cmd.sin_port = htons(PORTA_COMANDOS);
    end_cmd.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    end_tel = end_cmd;
    end_tel.sin_port = htons(PORTA_TELEMETRIA);
    if (sock < 0 || bind(sock, (struct sockaddr *)&end_cmd, sizeof end_cmd) < 0) {
        fprintf(stderr, "Porta UDP %d ocupada: ja existe outro pid_motor rodando?\n",
                PORTA_COMANDOS);
        encerrar(h);
        return 1;
    }

    struct timespec t0, next, now, ant, ultimo_painel;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    next = ant = ultimo_painel = t0;
    int painel_ativo = 0;          /* vira 1 quando chega o primeiro comando do painel */

    if (pid_direto) {
        char cmd[100];
        snprintf(cmd, sizeof cmd, "pid %s %s %s %s", argv[1], argv[2], argv[3], argv[4]);
        tratar_comando(cmd, 0.0, 0.0);
        if (modo != PID) {
            fprintf(stderr, "Setpoint deve ser > 0 e ganhos >= 0.\n");
            encerrar(h);
            return 1;
        }
        printf("PID direto: setpoint %g RPM | Kp %g Ki %g Kd %g | Ctrl+C para parar\n",
               setpoint, kp, ki, kd);
    } else {
        printf("Parado, esperando comandos do painel (python3 painel_c.py). "
               "Ctrl+C para sair.\n");
    }

    const double alpha = N_FILTRO * TS / (1.0 + N_FILTRO * TS);
    const long ts_ns = (long)(TS * 1e9);
    long prev_count = __atomic_load_n(&count, __ATOMIC_RELAXED);
    int negativas = 0;
    double u = 0.0;
    double u_aplicado = -1.0;      /* ultimo duty enviado ao PWM (-1 = nenhum ainda) */
    int ponte_ligada = 0;          /* IN1/IN2 em sentido +1? */

    while (running) {
        next.tv_nsec += ts_ns;                       /* proximo instante */
        if (next.tv_nsec >= 1000000000L) {
            next.tv_nsec -= 1000000000L;
            next.tv_sec++;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        if (!running) break;                         /* Ctrl+C no meio da espera */

        /* AJUSTE: RPM calculado com o intervalo realmente medido (nao o nominal) */
        clock_gettime(CLOCK_MONOTONIC, &now);
        double dt = segundos(ant, now);
        ant = now;
        long c = __atomic_load_n(&count, __ATOMIC_RELAXED);
        double rpm = SINAL_ENCODER * (double)(c - prev_count) / PPR / dt * 60.0;
        prev_count = c;

        /* Comandos pendentes do painel */
        char buf[128];
        ssize_t n;
        while ((n = recv(sock, buf, sizeof buf - 1, MSG_DONTWAIT)) > 0) {
            buf[n] = '\0';
            painel_ativo = 1;
            ultimo_painel = now;
            tratar_comando(buf, u, rpm);
        }
        /* Seguranca: painel fechado ou travado -> para o motor */
        if (painel_ativo && modo != PARADO && segundos(ultimo_painel, now) > TIMEOUT_PAINEL) {
            fprintf(stderr, "Sem sinal do painel ha %.0f s: motor parado.\n", TIMEOUT_PAINEL);
            modo = PARADO;
            fechar_csv();
        }

        double e = setpoint - rpm;
        if (modo == PID) {
            /* AJUSTE: protecao - RPM negativo por 0,2 s seguidos indica sinal do
             * encoder trocado (realimentacao positiva). Para o motor. */
            if (rpm < -10.0) {
                if (++negativas >= 10) {
                    fprintf(stderr, "Velocidade negativa: confira SINAL_ENCODER. Parando.\n");
                    modo = PARADO;
                    aviso = 1;
                    fechar_csv();
                    if (pid_direto) break;
                }
            } else {
                negativas = 0;
            }
        }

        if (modo == PID) {
            d_f += alpha * ((e - e_prev) / TS - d_f);   /* derivada filtrada */
            double I_new = I + ki * e * TS;
            double u_raw = kp * e + I_new + kd * d_f;
            u = u_raw < 0.0 ? 0.0 : (u_raw > DUTY_MAX ? DUTY_MAX : u_raw);
            if (u == u_raw) I = I_new;                   /* anti-windup */
            e_prev = e;
        } else if (modo == MANUAL) {
            u = duty_manual;
        } else {
            u = 0.0;
        }

        /* AJUSTE: ponte H so habilitada fora do modo parado */
        if (modo != PARADO && !ponte_ligada) {
            lgGpioWrite(h, IN1, 1);                      /* sentido de giro (+1) */
            lgGpioWrite(h, IN2, 0);
            ponte_ligada = 1;
        } else if (modo == PARADO && ponte_ligada) {
            lgGpioWrite(h, IN1, 0);
            lgGpioWrite(h, IN2, 0);
            ponte_ligada = 0;
        }
        /* AJUSTE: o PWM so e reaplicado quando o duty muda. Chamar lgTxPwm a cada
         * 20 ms reinicia a onda e pode gerar pulsos espurios (apito no motor parado). */
        double du = u - u_aplicado;
        if (du > 0.05 || du < -0.05) {
            lgTxPwm(h, PWM_PIN, PWM_FREQ, (float)u, 0, 0);   /* duty em % */
            u_aplicado = u;
        }

        double t = segundos(t0, now);
        if (arq && modo == PID)
            fprintf(arq, "%.3f,pid,%.1f,%.2f,%.1f,%.2f,%g,%g,%g,%.2f\n",
                    t, setpoint, rpm, u, e, kp, ki, kd, dt * 1e3);
        else if (arq)   /* manual: sem setpoint nem erro, como no painel em Python */
            fprintf(arq, "%.3f,manual,,%.2f,%.1f,,%g,%g,%g,%.2f\n",
                    t, rpm, u, kp, ki, kd, dt * 1e3);

        char tel[300];
        const char *base = strrchr(nome_arq, '/');
        int len = snprintf(tel, sizeof tel, "%.3f,%s,%.2f,%.2f,%.2f,%.2f,%g,%g,%g,%d,%s",
                           t, NOME_MODO[modo], setpoint, rpm, u, e, kp, ki, kd, aviso,
                           base ? base + 1 : nome_arq);
        sendto(sock, tel, len, MSG_DONTWAIT, (struct sockaddr *)&end_tel, sizeof end_tel);
    }

    encerrar(h);
    fechar_csv();
    printf("Motor parado.\n");
    return 0;
}
