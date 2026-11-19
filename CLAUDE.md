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

## Estrutura do repositório (proposta)

```
.
├── CLAUDE.md
├── README.md                 # visão geral + como rodar
├── pid/
│   ├── config.py             # pinos, Ts, ganhos, limites
│   ├── motor.py              # acionamento PWM/direção via L298N
│   ├── encoder.py            # leitura do encoder e cálculo de RPM
│   ├── pid.py                # controlador PID discreto (independente de hardware)
│   ├── main.py               # laço de controle
│   ├── testes/               # testes que rodam no PC, sem a Pi (GPIO simulado)
│   ├── dados/                # CSVs de ensaios (nome com data e descrição)
│   └── analise/              # scripts/notebooks de gráficos e identificação
├── ssh-bluetooth/
│   ├── README.md
│   ├── config/
│   └── setup.sh
└── docs/
    ├── referencias/
    └── relatorio/
```

Se a estrutura existente divergir desta, siga a que existe e atualize este arquivo.

### Código antigo (`controle_antigo/`) e versões

- `controle_antigo/` é a **v0**: o código que já funcionava antes do repositório.
  **Por enquanto (decisão de 2026-11-19), a v0 recebe correções diretas**, com foco em
  simplicidade e em ser fácil de ajustar e entender. A v1 começa depois. O estado
  original da v0 fica no commit `c7e9ecc` ("Código antigo"), que serve de base de
  comparação.
- Calibração e sinal do encoder ficam **só** em `controle_antigo/hardware.py`
  (`CONTAGENS_POR_VOLTA`, `SINAL_ENCODER`, `contagens_para_rpm`).
- O painel grava os ensaios direto em `pid/dados/`, com cabeçalho `#`. Na Pi, use o clone
  do repositório (`~/Controle2`) para que os CSVs possam ser commitados de lá.
- Melhorias são feitas em cima dela em **versões numeradas (v1, v2, v3…)**, cada uma
  comparável com a anterior e com a v0 (ex.: `git diff --no-index <arquivo_v0> <arquivo_v1>`).
  Cada versão deve registrar o que mudou e por quê (material para o relatório).
- Conteúdo da v0 (ordem de uso em `controle_antigo/LEIA-ME.txt`):
  `girar.py` (teste mínimo da ponte H), `contar_pulsos.py` (canais do encoder com o eixo
  girado à mão), `teste_motor.py` (malha aberta interativa), `calibrar_encoder.py`
  (contagens por volta), `painel.py` + `painel.html` (painel web com malha aberta, PID e
  gravação de CSV), `hardware.py` (pinos, `DUTY_MAX`, classes `Motor` e `Encoder`),
  `pid.py` (PID discreto).
- Pontos em aberto na v0: `DUTY_MAX = 50` ainda não medido com multímetro, calibração
  do encoder preliminar e configuração misturada com o acesso ao GPIO em `hardware.py`.

## Regras de engenharia

- **Separar lógica de hardware.** `pid.py` não importa nada de GPIO; recebe medida e
  retorna ação de controle. Isso permite testar no PC (Windows) sem a Pi.
- **Período de amostragem (Ts) fixo e explícito** em `config.py`. Medir o Ts real no
  laço e registrar nos logs — jitter importa para a discussão de controle digital.
- PID discreto com **saturação do PWM (0–100 %)** e **anti-windup**. Documentar a forma
  de discretização usada.
- Todo ensaio gera um CSV em `pid/dados/` com: tempo, referência, RPM medido, ação de
  controle, e um cabeçalho/comentário com ganhos, Ts e condições do teste.
- Segurança: GPIO da Pi é **3,3 V e não tolera 5 V**. Antes de sugerir qualquer ligação,
  conferir níveis de tensão. Sempre GND comum entre Pi, L298N e fonte. Código deve
  parar o motor (PWM = 0) ao sair, inclusive em Ctrl+C/exceção.
- Dependências em `requirements.txt`. Biblioteca de GPIO escolhida: **`lgpio`**
  (`sudo apt install -y python3-lgpio`, chip `gpiochip0` na Pi 4). Encoder lido por
  callbacks nas duas bordas dos dois canais (quadratura 4x); PWM por `lgpio.tx_pwm`.
  Só um script pode usar os GPIO por vez.
- Ts da v0: **0,05 s (20 Hz)**, definido em `controle_antigo/painel.py`.
- Discretização do PID na v0 (`controle_antigo/pid.py`): forma posicional; integral por
  Euler retangular (`I += Ki·e·T`); derivada sobre a medida (não sobre o erro) com filtro
  passa-baixa de 1ª ordem (`alfa_d = 0,7`); anti-windup por integração condicional;
  saída saturada entre 0 e 100 %. Relação com os artigos: `Kp = Kc`, `Ki = Kc/Ti`,
  `Kd = Kc·Td`.

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

- `main` é protegida: **nada de commit direto**. Uma branch por tarefa:
  `pid/<descricao>`, `ssh/<descricao>`, `docs/<descricao>`.
- Commits pequenos, mensagem em português no imperativo
  (ex.: `Adiciona leitura do encoder por interrupção`).
- Toda mudança entra via **Pull Request** com: o que mudou, como foi testado
  (PC ou Pi, com qual resultado) e prints/CSVs quando houver ensaio.
- Antes de abrir PR: `git pull --rebase origin main`, rodar os testes de `pid/testes/`.
- Issues do GitHub = lista de tarefas do grupo. Referenciar a issue no PR (`Closes #N`).
- Não commitar: `__pycache__/`, `.venv/`, chaves, senhas, arquivos grandes de mídia.

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
  - 2026-11-19 — painel aberto no navegador da própria Pi. Acesso pelo PC ainda não testado.
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
  - Pendente: confirmar a calibração, medir `DUTY_MAX`, primeiro ensaio em malha fechada
    (PI), acessar o painel pelo PC.
- SSH Bluetooth: _preencher (ex.: rede BT sobe no boot? IP/porta conferidos?)_
