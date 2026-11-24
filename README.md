# Controle Digital — Trabalho prático

Trabalho em grupo da disciplina **Controle Digital** (Engenharia da Computação):
controle digital de velocidade (RPM) de um motor DC com PID, rodando numa
Raspberry Pi 4. **O controlador é escrito em C** (Ts = 20 ms), e há um painel web
com gráficos em tempo real. A Pi é acessada pelo PC (Windows 11) por SSH sobre uma
rede Bluetooth, sem monitor e sem internet.

| Pasta | Conteúdo |
|---|---|
| [`controle_c/`](controle_c/) | **Código que roda na Pi:** `pid_motor.c` (controlador em C, lgpio), `painel_c.py` + `painel.html` (painel web em tempo real) |
| [`pid/dados/`](pid/dados/) | CSVs de todos os ensaios: `pidc_`/`manualc_` (C) e `pid_`/`manual_` (versão em Python) |
| [`pid/analise/`](pid/analise/) | Scripts que rodam **no PC**: identificação da planta, sintonia Ziegler–Nichols e previsão do roteiro de ganhos |
| [`pid/testes/`](pid/testes/) | Testes automáticos da análise e da cópia do PID do C (rodam no PC, sem a Pi) |
| [`ssh-bluetooth/`](ssh-bluetooth/) | Acesso SSH à Pi pela rede Bluetooth |
| [`docs/`](docs/) | Referências bibliográficas e relatório |

**Versão anterior em Python:** o controlador e o painel em Python (Ts = 50 ms) e as
ferramentas de bancada (`girar.py`, `contar_pulsos.py`, `teste_motor.py`,
`calibrar_encoder.py`) estão na branch
[`Projeto_Controle_Python`](https://github.com/CorradiniE/Controle2/tree/Projeto_Controle_Python).
Use essa branch para recalibrar o encoder ou testar a ligação do hardware.

Contexto completo (hardware, pinagem, decisões de controle, status dos ensaios):
[`CLAUDE.md`](CLAUDE.md).

---

## 1. Hardware e segurança (ler antes de ligar)

- Pinagem conferida: tabela em [`CLAUDE.md`](CLAUDE.md#1-controlador-pid-de-rotação-de-motor-dc-pid).
- **GPIO da Pi é 3,3 V.** Nada nos pinos 2 e 4 (5 V) nem no borne +5V do L298N.
- **GND comum** entre Pi, L298N e fonte externa.
- `DUTY_MAX = 50 %` (em `controle_c/pid_motor.c`) protege o motor de 6 V alimentado
  com uma fonte de até 12 V. Nenhum comando passa desse valor.
- Para parar o motor: botão **PARAR** no painel, tecla **Esc** na página, ou
  **Ctrl+C** no terminal do `pid_motor`. **Se o painel for fechado, o `pid_motor`
  para o motor em 2 s.** Se a velocidade medida ficar negativa no PID (encoder com
  o sinal trocado), ele também para o motor sozinho.
- **Só um programa pode usar os GPIO por vez.**

---

## 2. Configuração inicial (uma vez só)

### 2.1 No PC (Windows 11)

Precisa de **Git**, **Python 3** e do **OpenSSH** (já vem no Windows 11).

```powershell
git clone https://github.com/CorradiniE/Controle2.git
cd Controle2
gh auth login
gh auth setup-git
```

O `gh auth` faz login no GitHub com permissão de escrita, que é o que permite o
`git push`. Para os gráficos da análise, que são opcionais: `pip install matplotlib`.

### 2.2 Na Raspberry Pi

A Pi **não tem internet** durante os ensaios: só a rede Bluetooth com o PC. O código
chega a ela pelo PC, via SSH (seção 2.3). Para instalar pacotes, use a **ponte SSH**
(seção 2.4).

1. Conecte-se pelo PC com `ssh enzo@192.168.50.1`. IP e rede estão em
   [`ssh-bluetooth/README.md`](ssh-bluetooth/README.md).
2. Instale a lgpio com o cabeçalho para C, pela ponte SSH:
   ```
   sudo apt install -y liblgpio-dev
   ```
   O Raspberry Pi OS atual (Debian 13 trixie) **não tem a pigpio**. Por isso o
   controlador usa a lgpio.
3. Crie o clone em `~/Controle2`, de um destes dois jeitos:
   - **Com a ponte SSH aberta:**
     `git -c http.proxy=socks5h://127.0.0.1:1080 clone https://github.com/CorradiniE/Controle2.git ~/Controle2`
   - **Sem a ponte:** no PC, rode `git bundle create Controle2.bundle main` e
     `scp Controle2.bundle enzo@192.168.50.1:/home/enzo/`. Na Pi, rode
     `git clone ~/Controle2.bundle ~/Controle2`.
4. Deixe a Pi aceitar atualizações enviadas pelo PC e configure o autor dos commits.
   Use o seu e-mail **noreply** do GitHub, em <https://github.com/settings/emails>.
   Com o e-mail pessoal, o GitHub **recusa o push** (erro GH007).
   ```
   cd ~/Controle2
   git config receive.denyCurrentBranch updateInstead
   git config user.name "Seu Nome"
   git config user.email "NUMERO+usuario@users.noreply.github.com"
   ```

### 2.3 Ligar o PC à Pi pelo Git (no PC)

```powershell
git remote add pi ssh://enzo@192.168.50.1/home/enzo/Controle2
```

Daqui em diante:
- **PC → Pi** (código novo): `git push pi main`.
- **Pi → PC** (ensaios novos): `git pull pi main`.
- **PC → GitHub:** `git push origin main`.

### 2.4 Ponte SSH: internet do PC emprestada para a Pi

Num PowerShell à parte, deixe aberto:
```powershell
ssh -R 1080 enzo@192.168.50.1
```
Na Pi, passe o proxy para o `apt`, o `git` ou o `curl`:
```
P=socks5h://127.0.0.1:1080
sudo apt -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P install -y <pacote>
git -c http.proxy=$P pull origin main
curl -x $P -sI https://github.com | head -1        # teste: HTTP/2 200
```

---

## 3. Passo a passo de uma sessão de ensaios

**Qual janela usar para cada comando:**

| Janela | Prompt | Comandos |
|---|---|---|
| **PowerShell do PC** | `PS C:\...>` | `git push pi`, `git pull pi`, `scp`, `ssh` |
| **Terminal da Pi** (via SSH) | `enzo@RASP4:~ $` | `gcc`, `./pid_motor`, `python3`, `apt` |

### 3.1 Preparar (no PC)

```powershell
cd Controle2
git pull origin main
git push pi main
```

Este passo traz as novidades do GitHub e as manda para a Pi. Se ela já estiver
igual, o Git responde `Everything up-to-date`, e está tudo certo.

### 3.2 Acertar o relógio da Pi (no PC)

Sem internet, o relógio da Pi atrasa. A hora errada vai para o nome dos CSVs e para
os commits.

```powershell
ssh -t enzo@192.168.50.1 "sudo date -s '$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')'"
```

### 3.3 Compilar o controlador (na Pi)

Rode sempre que o `pid_motor.c` mudar:

```
cd ~/Controle2/controle_c
gcc -O2 -Wall -o pid_motor pid_motor.c -llgpio
```

A compilação tem que terminar **sem nenhuma mensagem**. Se aparecer `warning` ou
`error`, não rode.

### 3.4 Subir o controlador e o painel (na Pi, em dois terminais SSH)

```
# terminal 1: o controlador (fica parado esperando comandos)
cd ~/Controle2/controle_c && ./pid_motor

# terminal 2: o painel web
cd ~/Controle2/controle_c && python3 painel_c.py
```

Esperado no terminal 1: `Parado, esperando comandos do painel...`. No terminal 2:
`Painel (C) no ar: http://localhost:8000 ...`. Deixe os dois abertos.

**Sem painel**, com o PID ligado direto (setpoint, Kp, Ki, Kd):
`./pid_motor 40 1.5 7.5 0`. O `Ctrl+C` para o motor.

### 3.5 Abrir o painel

- Pelo navegador da Pi: `http://localhost:8000`.
- Pelo PC, abra mais um PowerShell e crie um túnel:
  ```powershell
  ssh -L 8000:localhost:8000 enzo@192.168.50.1
  ```
  Depois abra `http://localhost:8000` no navegador do PC.

### 3.6 Fazer um ensaio

Protocolo padrão (todo ensaio parte do mesmo ponto, para as curvas serem comparáveis):

1. **Malha aberta:** duty `20` → **Aplicar duty**. Espere ~3 s (o motor estabiliza em ~11 RPM).
2. **PID:** Setpoint `40`, Kp, Ki e Kd do ensaio → **Iniciar / atualizar PID**.
   Observe por ~8 s.
3. **Malha aberta:** duty `20` → **Aplicar duty**. Isso fecha o CSV do ensaio.
   Vá para o próximo.
4. No fim: **PARAR**. Depois, **Ctrl+C** nos dois terminais.

Regras importantes:
- **Setpoint de até ~55 RPM.** Com `DUTY_MAX = 50 %` a velocidade máxima é de ~67 RPM.
  Acima disso o duty trava em 50 % e os ganhos não fazem diferença.
- Partir de 20 % (e não do motor parado) evita a zona morta do motor (abaixo de
  ~15 % de duty ele não gira).
- Cada conjunto de ganhos gera **um CSV próprio** em `pid/dados/`, por exemplo
  `pidc_20261124_154209_kp1.5_ki7.5_kd0.csv`. Mudar só o setpoint continua no mesmo
  arquivo. A coluna `dt_ms` traz o período medido de cada amostra (jitter).
- A velocidade varia em **passos de 0,88 RPM**, que é 1 contagem do encoder a cada
  20 ms. Isso é a resolução da medida, e não oscilação do controle.

### 3.7 Roteiro de ganhos

Previsão por simulação, com o PID do C a Ts = 20 ms:
[`pid/analise/resultados/roteiro_ganhos.txt`](pid/analise/resultados/roteiro_ganhos.txt).

| Ens. | Kp | Ki | Kd | Comportamento esperado |
|---|---|---|---|---|
| A1 | 0.3 | 0 | 0 | Lento, para longe do setpoint (erro de ~18 RPM) |
| A2 | 1.0 | 0 | 0 | Mais rápido, erro menor (~9 RPM) |
| A3 | 3.0 | 0 | 0 | Overshoot pequeno, ainda com erro (~4 RPM), duty ruidoso |
| A4 | 8.0 | 0 | 0 | Oscilação sustentada |
| B1 | 1.5 | 1 | 0 | Sem overshoot, chega devagar (~3 s) |
| B2 | 1.5 | 3 | 0 | Sem overshoot, ~1 s |
| B3 | 1.5 | 7.5 | 0 | **Referência:** rápido e sem overshoot (validado na bancada) |
| B4 | 1.5 | 30 | 0 | Overshoot de ~10 % |
| B5 | 1.5 | 35 | 0 | Overshoot de ~15 % e oscilação que demora a sumir |
| B6 | 1.5 | 40 | 0 | Oscilação sustentada |
| C1 | 0.3 | 7.5 | 0 | Overshoot grande (~38 %) e lento |
| C2 | 0.7 | 7.5 | 0 | Overshoot médio (~17 %) |
| C3 | 4.0 | 7.5 | 0 | Oscila, duty muito ruidoso |
| D1 | 1.5 | 7.5 | 0.05 | Quase igual ao B3, duty um pouco mais ruidoso |
| D2 | 1.5 | 7.5 | 0.1 | A derivada amplifica o ruído |
| D3 | 1.5 | 7.5 | 0.2 | Overshoot de ~10 % e duty ruidoso |
| D4 | 1.5 | 7.5 | 0.3 | Kd demais: oscila |
| Z1 | 2.01 | 13.24 | 0 | PI de Ziegler–Nichols refeito para Ts = 20 ms: ~1 % de overshoot |
| Z2 | 2.68 | 29.39 | 0.061 | PID de Ziegler–Nichols para Ts = 20 ms: oscila |

A4, B6, C3, D4 e Z2 fazem o duty bater entre 0 e 50 %. Se houver vibração forte,
aperte **Esc**. Para testar rejeição de perturbação, segure o eixo com o PID em regime.

### 3.8 Anotar e salvar os ensaios

1. Na Pi, anote o que aconteceu na linha `# Condicoes/observacoes` do CSV
   (ex.: `segurei o eixo em t = 12 s`), com `nano ~/Controle2/pid/dados/<arquivo>.csv`.
2. Faça o commit na Pi:
   ```
   cd ~/Controle2
   git add pid/dados/
   git commit -m "Adiciona ensaios <descrição>"
   ```
3. Leve para o GitHub (no PC):
   ```powershell
   git pull pi main
   git push origin main
   ```

---

## 4. Análise no PC

```powershell
# Modelo da planta + ganhos Ziegler–Nichols a partir de um ensaio de malha aberta
python pid/analise/identificacao_zn.py pid/dados/<ensaio_manual>.csv --metodo smith --atraso-zoh

# Previsão do roteiro de ganhos (gera pid/analise/resultados/roteiro_ganhos.txt)
python pid/analise/roteiro_ganhos.py

# Testes automáticos
python -m unittest discover -s pid/testes -v
```

As simulações usam [`pid/analise/pid_c.py`](pid/analise/pid_c.py), uma cópia em
Python da lei de controle do `pid_motor.c`. **Se mudar o PID no C, mude ali também.**
O `--ts` padrão é 0,02 s (o do C). Para os ensaios de malha aberta da versão em
Python, que têm velocidade negativa (gravados antes de `SINAL_ENCODER = -1`), use
`--inverter-sinal`. Para ignorar o trecho com perturbação, use `--ate <tempo>`.
Os resultados vão para `pid/analise/resultados/`.

---

## 5. Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| Comando de PC rodado na Pi (`scp "C:\..."`, ou `ssh enzo@192.168.50.1` pedindo a chave da própria Pi) | Janela errada | `scp`/`git push pi` vão no **PowerShell do PC**; `gcc`, `./pid_motor` e `python3` vão no **terminal da Pi** |
| Painel: `Sem dados do pid_motor` | O `./pid_motor` não está rodando | Suba o `pid_motor` no terminal 1 |
| `pid_motor`: `GPIO ocupado` | Outro programa está usando os GPIO | `pgrep -af "pid_motor\|python"` e encerre o outro |
| `pid_motor`: `Porta UDP 5006 ocupada` | Já existe outro `pid_motor` rodando | `pkill pid_motor` |
| `lgpio.h: No such file` / `pigpio.h: No such file` | Falta o `liblgpio-dev`; a pigpio não existe no trixie | `sudo apt install -y liblgpio-dev` pela ponte SSH (2.4) |
| Navegador: "site can't be reached" / `raspberrypi.local` | O nome da Pi é `RASP4`, e o painel precisa estar rodando | `localhost:8000` na Pi, ou o túnel SSH no PC (3.5) |
| "Velocidade negativa: confira SINAL_ENCODER" | Sinal do encoder invertido | `SINAL_ENCODER` em `controle_c/pid_motor.c` |
| Duty travado em 50 % e todas as curvas iguais | Setpoint inalcançável | Use setpoint ≤ ~55 RPM |
| `Could not resolve host: github.com` na Pi | A Pi está sem internet | Use `git push pi main` / `git pull pi main` pelo PC, ou a ponte SSH (2.4) |
| `fatal: not a git repository` | Comando rodado fora da pasta do projeto | `cd` para a pasta do clone |
| `GH007: Your push would publish a private email address` | Commit com e-mail pessoal | Configure o e-mail noreply (2.2) e corrija o commit com `git commit --amend --reset-author --no-edit` |
| `403` / `Permission denied` no push | Login sem permissão de escrita | `gh auth refresh -h github.com -s repo` e `gh auth setup-git` |
| `divergent branches` no pull | Commits diferentes no PC e na Pi | `git pull --no-rebase pi main` (gera um merge) |
| Commit com hora errada no GitHub | Relógio da Pi atrasado | Acerte a hora antes dos ensaios (3.2) |

---

## 6. Fluxo de trabalho do grupo

- Mensagens de commit em português, no imperativo (`Adiciona ...`, `Corrige ...`).
- Ensaios (CSVs) vão para `pid/dados/` **sempre**, inclusive os que deram errado,
  com uma observação no cabeçalho dizendo o que aconteceu.
- Antes de mudar código: `python -m unittest discover -s pid/testes` no PC.
- Mudanças de código devem ser feitas no PC e enviadas para a Pi com `git push pi main`.
  **Não edite o código direto na Pi.** Isso cria versões divergentes que depois
  precisam ser juntadas à mão.
- Branches:
  - `main`: versão final, controlador em C;
  - `Projeto_Controle_Python`: versão em Python e ferramentas de calibração;
  - `Código-Controlador-C`: código em C original do colega, para pigpio. Não roda na
    Pi atual, e foi a base do `controle_c/`.
