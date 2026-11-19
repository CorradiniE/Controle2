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

**Pinagem** (preencher quando definida — fonte única de verdade, o código deve importar daqui ou de `pid/config.py`)
| Sinal | GPIO (BCM) | Pino físico |
|---|---|---|
| L298N ENA (PWM) | _a definir_ | |
| L298N IN1 | _a definir_ | |
| L298N IN2 | _a definir_ | |
| Encoder canal A | _a definir_ | |
| Encoder canal B | _a definir_ | |

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
- Dependências em `requirements.txt`. Registrar aqui a biblioteca de GPIO escolhida:
  _a definir_.

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

- PID: _preencher (ex.: ligação do L298N testada? encoder lendo? malha aberta medida?)_
- SSH Bluetooth: _preencher (ex.: rede BT sobe no boot? IP/porta conferidos?)_
