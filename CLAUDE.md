# CLAUDE.md — Projeto Controle Digital

Este arquivo dá contexto ao Claude Code sobre o repositório. Ele é lido automaticamente
no início de cada sessão. **Mantenha-o atualizado** (principalmente a seção "Status atual").

## Contexto

- Disciplina: **Controle Digital** — Engenharia da Computação, trabalho em grupo.
- O repositório reúne o trabalho **prático** da disciplina. O resultado final vira um
  **relatório acadêmico**, então decisões, parâmetros e resultados de teste precisam
  ficar documentados e reproduzíveis.
- Idioma: tudo em **português** (código pode ter nomes em inglês ou português, mas
  comentários, docs, commits e PRs em português).

## Frentes de trabalho

### 1. Controlador PID de rotação de motor DC (`pid/`)

Controlador digital de velocidade (RPM) de um motor DC, rodando na Raspberry Pi, em Python.

**Hardware**
| Item | Detalhe |
|---|---|
| Controlador | Raspberry Pi 4 Model B (Raspberry Pi OS) |
| Driver | Ponte H L298N |
| Motor | JGA25-370-CE, etiqueta **DC 6V 100 RPM** (velocidade de saída, após a redução) |
| Encoder | Integrado ao motor, placa indica alimentação **3,3 V** |
| Alimentação | Fonte externa para o motor (GND comum com a Pi) |
| Bancada | Multímetro, protoboard, resistores (para divisor de tensão se necessário) |

**Pinagem** (conferida na bancada em 2026-11-18. É a fonte única de verdade: o código deve
importar daqui ou de `pid/config.py`)
| Sinal | GPIO (BCM) | Pino físico | Observação |
|---|---|---|---|
| L298N ENA (PWM) | 18 | 12 | PWM a 1 kHz; jumper ENA **retirado** |
| L298N IN1 | 23 | 16 | |
| L298N IN2 | 24 | 18 | |
| Encoder canal A (C1) | 17 | 11 | fio amarelo, pull-up interno |
| Encoder canal B (C2) | 27 | 13 | fio verde, pull-up interno |
| Encoder VCC | — | 1 (3,3 V) | fio azul |
| Encoder GND | — | 9 | fio preto |
| L298N GND | — | 6 | mesmo borne do negativo da fonte externa |

Motor: vermelho → OUT1, branco → OUT2. Fonte externa: (+) → borne +12V do L298N,
(−) → GND do L298N. **Nada** ligado aos pinos 2 e 4 (5 V) da Pi nem ao borne +5V do L298N.

**Base bibliográfica obrigatória** (o método e a discussão do relatório devem se apoiar nela):
- Kolya et al. (2021)
- Razali et al. (2019)
- Herrera-Aristizábal et al. (2020)

Os PDFs/referências completas ficam em `docs/referencias/`. Não inventar citações nem
resultados atribuídos a esses artigos — se precisar de algo deles, peça o trecho.

### 2. Acesso SSH via Bluetooth (`ssh-bluetooth/`)

- Objetivo: conectar o PC à Raspberry Pi **por Bluetooth (não Wi-Fi)**, acessar via SSH,
  iniciar o software de controle do motor e deixar a Pi controlando de forma autônoma.
  A placa **não** é ligada a monitor — todo contato é por SSH.
- O PC cliente usa **Windows 11**.
- Já foi configurada antes uma rede sobre Bluetooth com IP e porta dedicados
  (registrar os valores em `ssh-bluetooth/README.md` assim que forem conferidos).
- O que vai para o Git nesta pasta: passo a passo de configuração (Pi e Windows),
  arquivos de configuração/serviços (ex.: unidades systemd, config de rede) e scripts
  de setup — para qualquer pessoa do grupo conseguir reproduzir.
- **Nunca** commitar chaves SSH, senhas ou endereços MAC pessoais sem necessidade.

## Estrutura do repositório e branches

**Decisão de 2026-11-24:** a `main` é a **versão final do projeto, com o controlador
em C**. Tudo o que era da versão em Python (controlador, painel e ferramentas de
bancada) foi para a branch **`Projeto_Controle_Python`**.

```
.                                   (branch main)
├── CLAUDE.md
├── README.md                 # passo a passo completo para o grupo
├── requirements.txt          # dependências da análise no PC (matplotlib, opcional)
├── controle_c/               # roda na Pi
│   ├── pid_motor.c           # controlador em C (lgpio, Ts = 20 ms): PID, encoder, PWM,
│   │                         #   CSV por ensaio, comandos/telemetria por UDP
│   ├── painel_c.py           # servidor web do painel (não usa GPIO; ponte UDP)
│   └── painel.html           # página com gráficos em tempo real
├── pid/
│   ├── dados/                # CSVs de todos os ensaios (C e Python)
│   ├── analise/              # roda no PC: identificação, ZN, roteiro de ganhos,
│   │                         #   pid_c.py = cópia em Python da lei de controle do C
│   └── testes/               # testes no PC (análise e pid_c.py)
├── ssh-bluetooth/
└── docs/
    ├── referencias/
    └── relatorio/
```

- **`main`**: versão final (C). A pasta `controle_antigo/` saiu daqui.
- **`Projeto_Controle_Python`**: o estado da `main` em 2026-11-24 antes da troca
  (commit `a1ea6b0`), com um aviso no README. Contém `controle_antigo/`:
  - controlador e painel em Python (Ts = 50 ms);
  - ferramentas de bancada: `girar.py`, `contar_pulsos.py`, `teste_motor.py`,
    `calibrar_encoder.py`, que **continuam sendo o jeito de recalibrar o encoder**.
- **`Código-Controlador-C`**: o `Código PID` original do colega (FSLouredo), para
  pigpio. Não compila no Debian 13 da Pi. Foi a base do `controle_c/pid_motor.c`.
- O estado original da v0 em Python fica no commit `c7e9ecc` ("Código antigo").
- Calibração e sinal do encoder, na versão em C: `PPR` e `SINAL_ENCODER` em
  `controle_c/pid_motor.c`.
- **A lei de controle está em dois lugares:** `pid_motor.c` (roda na Pi) e
  `pid/analise/pid_c.py` (simulação no PC). Mudou um, mude o outro.
- Pontos em aberto: `DUTY_MAX = 50` ainda não medido com multímetro; calibração do
  encoder preliminar; configuração (pinos, Ts, limites) no topo do `pid_motor.c`, e não
  num arquivo separado.

## Regras de engenharia

- **Separar lógica de controle e simulação.** A lei de controle do C tem uma cópia em
  Python (`pid/analise/pid_c.py`), testada no PC sem a Pi.
- **Período de amostragem (Ts) fixo e explícito** (`TS` em `pid_motor.c`). O Ts real é
  medido no laço e gravado no CSV (`dt_ms`): o jitter importa para a discussão de
  controle digital.
- PID discreto com **saturação do PWM (0–100 %)** e **anti-windup**. Documentar a forma
  de discretização usada.
- Todo ensaio gera um CSV em `pid/dados/` com: tempo, referência, RPM medido, ação de
  controle, e um cabeçalho/comentário com ganhos, Ts e condições do teste.
- Segurança: GPIO da Pi é **3,3 V e não tolera 5 V**. Antes de sugerir qualquer ligação,
  conferir níveis de tensão. Sempre GND comum entre Pi, L298N e fonte. Código deve
  parar o motor (PWM = 0) ao sair, inclusive em Ctrl+C/exceção.
- Biblioteca de GPIO: **`lgpio`** (C: `sudo apt install -y liblgpio-dev`, compilar com
  `-llgpio`; chip `gpiochip0` na Pi 4). A pigpio **não existe** no Raspberry Pi OS atual
  (Debian 13 trixie). Encoder lido por alertas nas duas bordas dos dois canais
  (quadratura 4x); PWM por `lgTxPwm` a 1 kHz. Só um programa pode usar os GPIO por vez.
- **Ts do controlador em C: 0,02 s (50 Hz).** Na versão em Python era 0,05 s.
- Discretização do PID em C (`controle_c/pid_motor.c`, igual em `pid/analise/pid_c.py`):
  - forma posicional;
  - integral por Euler retangular (`I += Ki·e·T`);
  - derivada **do erro**, com filtro passa-baixa de 1ª ordem
    (`d_f += α·((e − e_ant)/T − d_f)`, com `α = N·T/(1 + N·T)` e `N = 10`);
  - anti-windup por integração condicional;
  - saída saturada entre 0 e `DUTY_MAX = 50 %`.

  Ao entrar no modo PID, a integral começa no duty atual (sem tranco) e `e_ant = e`
  (sem pico da derivada). Relação com os artigos: `Kp = Kc`, `Ki = Kc/Ti`, `Kd = Kc·Td`.
- Na versão em Python (branch `Projeto_Controle_Python`), a derivada era **da medida**,
  com `alfa_d = 0,7`. Essa diferença vale comentar no relatório.
- Dependências do PC em `requirements.txt`.

## Como trabalhar comigo (Claude)

- Atue como **orientador de laboratório**: avance em **etapas pequenas e testáveis**.
  Em tudo que envolve hardware, proponha o teste, diga o resultado esperado e **espere
  o resultado real** antes da próxima etapa. Nunca assuma que um teste passou.
- Explique o porquê das decisões de controle (é material para o relatório).
- Antes de mudar algo grande, leia o código existente e este arquivo; se houver
  conflito entre os dois, pergunte.
- Não invente valores de hardware (PPR do encoder, relação de redução, tensões):
  se não estiver documentado aqui, pergunte ou proponha um teste para medir.

## Fluxo Git / GitHub (trabalho em grupo)

O passo a passo completo, para o grupo, está no [`README.md`](README.md). Resumo:

- **Prática atual (decisão de 2026-11-19): commit e push direto na `main`.** Branches e
  Pull Requests (`pid/...`, `ssh/...`, `docs/...`) ficam para mudanças grandes, como a v1.
  Antes de commitar ou dar push em nome do usuário, mostre as mudanças e peça o ok.
- **Três cópias do repositório:**
  - **GitHub** (`origin`);
  - **PC** (Windows);
  - **Pi** (`~/Controle2`), que **não tem internet** durante os ensaios.

  A Pi é sincronizada pelo PC, via SSH sobre a rede Bluetooth, com o remote `pi`
  (`ssh://enzo@192.168.50.1/home/enzo/Controle2`):
  - PC → Pi: `git push pi main`. A Pi tem `receive.denyCurrentBranch updateInstead`,
    então a pasta dela se atualiza sozinha.
  - Pi → PC: `git pull pi main`; depois, no PC, `git push origin main`.
- **Código se edita no PC, nunca direto na Pi.** Na Pi só se fazem commits de CSVs de
  ensaio. Edição direta na Pi já gerou uma história divergente: o commit `bca7488`, que
  ficou em `~/Controle2_rasp_antigo` na Pi, com um `pid.py` e um `teste.py` ainda não
  revisados.
- **Autor dos commits:** e-mail **noreply** do GitHub. Com o e-mail pessoal, o GitHub
  recusa o push (GH007). Commit ainda não enviado: corrigir com
  `git commit --amend --reset-author --no-edit`.
- **Relógio da Pi:** sem internet ele fica atrasado (no commit `132644a`, cerca de 2 h).
  Isso afeta o nome dos CSVs e a data dos commits. Acerte a hora pelo PC antes dos
  ensaios (README, seção 3.2).
- Commits pequenos, mensagem em português no imperativo
  (ex.: `Adiciona leitura do encoder por interrupção`).
- Antes de mudar código: rodar os testes de `pid/testes/` no PC.
- Não commitar: `__pycache__/`, `.venv/`, chaves, senhas, arquivos grandes de mídia,
  e-mails pessoais.

## Status atual

_Atualize a cada etapa concluída (data — o quê — quem)._

- PID:
  - 2026-11-18 — fiação conferida na bancada, igual à de `controle_antigo/LEIA-ME.txt`
    (pinagem acima) — grupo.
  - 2026-11-19 — `calibrar_encoder.py` (duty 30 %, 10 voltas, ~33 RPM): média de
    **3420,8 contagens/volta (4x)**, ou seja, 855,2 pulsos/volta em 1 canal. Desvio entre
    voltas de 181,6 (5,3 %), atribuído ao tempo de reação no Enter. **Valor preliminar:
    `CONTAGENS_POR_VOLTA = 3421`**, a confirmar girando o eixo à mão com `contar_pulsos.py`.
    — grupo.
  - 2026-11-19 — painel v0 acessível em **`http://rasp4.local:8000`** (hostname da Pi:
    `RASP4`). O `raspberrypi.local` que o `painel.py` sugere não funciona nesta Pi. Para
    o painel abrir, o `painel.py` precisa estar rodando. — grupo.
  - 2026-11-19 — painel aberto **pelo PC** em `rasp4.local:8000`. Correção de
    2026-11-24: antes eu tinha registrado "no navegador da Pi", por engano.
  - 2026-11-19 — ensaio de malha aberta, degrau de 20 % para 35 %
    (`pid/dados/2026-11-19_malha_aberta_degrau_20a35.csv`):
    - **O encoder está com o sinal invertido**: a velocidade sai negativa no sentido +1.
      O painel precisa de `SINAL_ENCODER = -1` antes do modo PID.
    - Ts real de 50,02 ms, desvio de 0,6 ms e máximo de 65 ms.
    - Modelo pelo método dos dois pontos (fit de 93 %):
      **G(s) = 2,17·e^(−0,036 s)/(0,221 s + 1)**, com K em RPM/%. A tangente deu
      τ = 0,36 s, mas com fit de só 80 %.
    - θ é menor que Ts (±25 ms de incerteza), então o tempo morto é praticamente não
      mensurável com Ts = 50 ms.
    - Na simulação, os ganhos ZN calculados com o θ medido fazem a malha oscilar.
      Calculados com θ + Ts/2 (`--atraso-zoh`), o PI estabiliza:
      Kp = 1,51, Ki = 7,50, Kd = 0, com cerca de 11 % de sobressinal e acomodação em ~2 s.
      O PID de ZN continua oscilando.
    - Checagem: 10,8 RPM a 20 % e 43,3 RPM a 35 %. A reta prevê 32,5 RPM a 30 %, e a
      calibração mediu 33.
    - Segurar o eixo à mão derrubou a velocidade de ~44,5 para ~34–38 RPM em malha
      aberta. Esse dado serve de comparação para a malha fechada.
    — grupo.
  - 2026-11-19 — v0 corrigida: `CONTAGENS_POR_VOLTA = 3421` e `SINAL_ENCODER = -1` em
    `hardware.py`. Endereço do painel pelo hostname real. CSVs com cabeçalho, gravados
    em `pid/dados/`.
  - 2026-11-20 — registro dos ensaios PID melhorado:
    - cada conjunto de ganhos vira um CSV próprio, com os ganhos no nome e no cabeçalho;
    - colunas `p_pct`, `i_pct` e `d_pct` com a contribuição de cada termo;
    - mudar só o setpoint continua no mesmo arquivo.
    Roteiro de 17 ensaios (grupos A: só P, B: PI variando Ki, C: PI variando Kp,
    D: PID variando Kd), com a previsão simulada em
    `pid/analise/resultados/roteiro_ganhos.txt` (`pid/analise/roteiro_ganhos.py`).
    Na simulação, Kd só aumenta o ruído no duty. Faz sentido: a planta é de 1ª ordem,
    com atraso pequeno, e o PI basta.
  - 2026-11-20 — 11 ensaios PID gravados com o painel anterior (`pid/dados/pid_20261120_*.csv`).
    - **10 deles usaram setpoint de 80 ou 100 RPM, que o motor não alcança:** com
      `DUTY_MAX = 50 %`, a velocidade máxima é de ~67–68 RPM. O duty ficou saturado em 50 %
      o tempo todo, e os ganhos não tiveram efeito. Esses 10 ensaios não servem para
      comparar ganhos. **Usar setpoint de até ~55 RPM.**
    - **Ensaio válido:** `pid_20261120_191050.csv`, PI com Kp = 1,51, Ki = 7,5 e Kd = 0,
      setpoint 43 RPM, partindo do repouso.
      - Chega a 42 RPM em ~0,6 s, sem overshoot.
      - Em regime: 43,0 RPM ± 0,5, com duty de ~31 %.
      - Com o eixo segurado à mão (em t ≈ 10, 11, 15 e 19 s), o duty sobe até 50 % e a
        velocidade volta a 43 RPM em ~1 s. Em malha aberta, a mesma perturbação deixava
        a velocidade em 34–38 RPM.
      - Bate com a previsão do roteiro (B3: sem overshoot, ~0,45 s).
  - 2026-11-20 — commit `132644a` "Adiciona ensaios do roteiro de ganhos A1-D4". Apesar
    da mensagem, ele traz **um só ensaio PID**
    (`pid_20261120_202620_kp1.51_ki7.5_kd0.csv`, equivalente ao B3) e dois manuais. O
    roteiro A1–D4 ainda não foi rodado por completo. Data do commit pelo relógio
    atrasado da Pi (20:27; no PC eram ~22:30).
  - 2026-11-20 — `README.md` com o passo a passo completo (configuração, sessão de
    ensaio, roteiro, análise e problemas comuns), para o grupo replicar.
  - 2026-11-24 — **controlador em C** (`controle_c/`). Base: arquivo `Código PID` da
    branch `Código-Controlador-C` (FSLouredo), escrito para a pigpio.
    - A pigpio não existe no Debian 13 (trixie) da Pi, então o acesso ao hardware foi
      portado para a lgpio. Foi preciso instalar `liblgpio-dev`, pela ponte SSH
      (`ssh -R 1080`), já que a Pi está sem Wi-Fi.
    - **O original não era seguro para o nosso hardware:** não tinha
      `SINAL_ENCODER = -1` (o PID dispararia até o máximo), saturava em 100 % em vez de
      `DUTY_MAX = 50`, e usava `PPR = 374*4` em vez de 3421. Os ganhos originais
      (2 / 40 / 0,1) oscilam no modelo do nosso motor. Ajustes marcados com `AJUSTE:`.
    - Diferenças em relação à v0 em Python: Ts = 20 ms; derivada calculada sobre o erro
      (e não sobre a medida), com filtro N = 10; anti-windup igual; RPM calculado com o
      intervalo realmente medido.
    - Primeiro ensaio (`pid/dados/pidc_20261124_154209_kp1.5_ki7.5_kd0.csv`): PI
      1,5 / 7,5 / 0, setpoint 40 RPM, partindo do repouso, 50 s de duração.
      - Subida de 10 % a 90 % em **0,34 s**, sem overshoot na subida.
      - Média de 39,99 RPM na segunda metade, com duty de ~30–31 %. A velocidade
        oscila entre 39,46 e 40,34 RPM: esse passo de 0,88 RPM é 1 contagem do encoder
        a cada 20 ms, a resolução da medida.
      - Quedas isoladas de uma amostra em t = 2,9, 37,6 e 43,6 s (a última até 24,6 RPM,
        com duty de 50 %), provavelmente toques no eixo, que não foram anotados.
      - **Jitter:** `dt_ms` com média de 19,999 ms e desvio de 0,053 ms (Python a 50 ms:
        desvio de 0,6 ms). A última linha (17,4 ms) é a interrupção pelo Ctrl+C, que o
        código atual já trata.
    - Painel em tempo real para o C: `controle_c/painel_c.py` serve a mesma
      `painel.html` e fala com o `pid_motor` por UDP local (telemetria na porta 5005,
      comandos na 5006). Testado no PC com um `pid_motor` simulado. **Ainda não
      testado na Pi.**
  - 2026-11-24 — **reestruturação:** a `main` passa a ser a versão final em C, e a
    versão em Python vai para a branch `Projeto_Controle_Python`.
    - `painel.html` foi movida para `controle_c/`.
    - Análise e testes passaram a simular o PID do C (`pid/analise/pid_c.py`, Ts = 20 ms).
    - Roteiro de ganhos refeito para Ts = 20 ms. Com o período menor, a malha fica mais
      estável, e os ganhos que mostram overshoot e oscilação mudaram: B4–B6 com Ki =
      30, 35 e 40; C3 com Kp = 4; D com Kd = 0,05 a 0,3.
    - Incluídos os ganhos de Ziegler–Nichols recalculados para Ts = 20 ms
      (`pid/analise/resultados/ts_20ms/`): PI com Kp = 2,01 e Ki = 13,24 (Z1,
      ~1 % de overshoot na simulação); PID com 2,68 / 29,39 / 0,061 (Z2, oscila).
  - 2026-11-24 — **painel do C funcionando na Pi**, aberto no PC em
    `http://192.168.50.1:8000`.
    - No Windows, `rasp4.local` resolve para 192.168.50.1 (o `ping` funciona), mas o
      Opera deu `DNS_PROBE_FINISHED_NXDOMAIN`, provavelmente por causa do DNS seguro
      ou da VPN do navegador. Use o IP.
    - `localhost:8000` no PC só funciona com túnel SSH.
  - Pendente:
    - rodar o roteiro de ganhos com o C (setpoint 40, Ts 20 ms);
    - confirmar a calibração;
    - medir `DUTY_MAX`;
    - rodar o roteiro A1–D4 completo (setpoint 40);
    - acessar o painel pelo PC (túnel SSH);
    - revisar `pid.py` e `teste.py` do commit `bca7488`, que estão só na Pi;
    - v1.
- SSH Bluetooth: _preencher (ex.: rede BT sobe no boot? IP/porta conferidos?)_
