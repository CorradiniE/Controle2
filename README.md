# Controle Digital — Trabalho prático

Trabalho em grupo da disciplina **Controle Digital** (Engenharia da Computação):
controle digital de velocidade (RPM) de um motor DC com PID, rodando numa
Raspberry Pi 4. A Pi é acessada pelo PC (Windows 11) por SSH sobre uma rede
Bluetooth, sem monitor e sem internet.

| Pasta | Conteúdo |
|---|---|
| [`controle_antigo/`](controle_antigo/) | **Código que roda na Pi (v0):** painel web, PID, acionamento do motor e leitura do encoder. Detalhes em [`LEIA-ME.txt`](controle_antigo/LEIA-ME.txt) |
| [`pid/dados/`](pid/dados/) | CSVs de todos os ensaios, gravados direto pelo painel |
| [`pid/analise/`](pid/analise/) | Scripts que rodam **no PC**: identificação da planta, sintonia Ziegler–Nichols e previsão do roteiro de ganhos |
| [`pid/testes/`](pid/testes/) | Testes automáticos dos scripts de análise (rodam no PC, sem a Pi) |
| [`ssh-bluetooth/`](ssh-bluetooth/) | Acesso SSH à Pi pela rede Bluetooth |
| [`docs/`](docs/) | Referências bibliográficas e relatório |

Contexto completo (hardware, pinagem, decisões de controle, status dos ensaios):
[`CLAUDE.md`](CLAUDE.md).

---

## 1. Hardware e segurança (ler antes de ligar)

- Pinagem conferida: tabela em [`CLAUDE.md`](CLAUDE.md#1-controlador-pid-de-rotação-de-motor-dc-pid)
  e em [`controle_antigo/LEIA-ME.txt`](controle_antigo/LEIA-ME.txt).
- **GPIO da Pi é 3,3 V.** Nada nos pinos 2 e 4 (5 V) nem no borne +5V do L298N.
- **GND comum** entre Pi, L298N e fonte externa.
- `DUTY_MAX = 50 %` (em `controle_antigo/hardware.py`) protege o motor de 6 V
  alimentado com uma fonte de até 12 V. Nenhum comando passa desse valor.
- Para parar o motor: botão **PARAR** no painel, tecla **Esc** na página ou
  **Ctrl+C** no terminal do `painel.py`. O motor para inclusive se der erro.
- **Só um script pode usar os GPIO por vez.** Feche um antes de abrir outro.

---

## 2. Configuração inicial (uma vez só)

### 2.1 No PC (Windows 11)

Precisa de **Git**, **Python 3** e do **OpenSSH** (já vem no Windows 11).

```powershell
git clone https://github.com/CorradiniE/Controle2.git
cd Controle2
```

Login no GitHub com permissão de escrita, que é o que permite o `git push`:

```powershell
gh auth login
gh auth setup-git
```

Opcional, para os gráficos da análise: `pip install matplotlib`.

### 2.2 Na Raspberry Pi

A Pi **não tem internet** durante os ensaios (só a rede Bluetooth com o PC).
O código chega a ela **pelo PC, via SSH** (seção 2.3).

1. Conecte-se pelo PC: `ssh enzo@192.168.50.1`. IP e rede estão em
   [`ssh-bluetooth/README.md`](ssh-bluetooth/README.md).
2. Instale a biblioteca de GPIO. Isso precisa de internet, então ligue o Wi-Fi
   (`sudo nmtui`) só para este passo:
   ```
   sudo apt install -y python3-lgpio
   ```
3. Crie o clone em `~/Controle2`, de um destes dois jeitos:
   - **Com internet:** `git clone https://github.com/CorradiniE/Controle2.git ~/Controle2`
   - **Sem internet:** no PC, rode `git bundle create Controle2.bundle main` e
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
cd Controle2
git remote add pi ssh://enzo@192.168.50.1/home/enzo/Controle2
```

Daqui em diante:
- **PC → Pi** (código novo): `git push pi main`.
- **Pi → PC** (ensaios novos): `git pull pi main`.
- **PC → GitHub:** `git push origin main`.

---

## 3. Passo a passo de uma sessão de ensaios

### 3.1 Preparar (no PC)

```powershell
cd Controle2
git pull origin main
git push pi main
```

Este passo traz as novidades do GitHub e as manda para a Pi. Se ela já estiver
igual, o Git responde `Everything up-to-date`, e está tudo certo.

### 3.2 Entrar na Pi e acertar o relógio

Sem internet, o relógio da Pi atrasa. A hora errada vai para o nome dos CSVs e
para os commits. No **PowerShell do PC**:

```powershell
ssh -t enzo@192.168.50.1 "sudo date -s '$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')'"
```

Depois entre na Pi:

```powershell
ssh enzo@192.168.50.1
```

### 3.3 Conferir a versão e subir o painel (na Pi)

```
cd ~/Controle2
git log --oneline -1
cd controle_antigo
python3 painel.py
```

Esperado:

```
Painel no ar: http://localhost:8000 (na Pi) ou http://rasp4.local:8000 (na rede)
Ensaios gravados em: /home/enzo/Controle2/pid/dados
Ctrl+C para encerrar.
```

**Deixe esse terminal aberto.** Se ele voltar ao prompt, o painel não está no ar
(veja a seção 5).

### 3.4 Abrir o painel

- Pelo navegador da Pi: `http://localhost:8000`.
- Pelo PC, abra um segundo PowerShell e crie um túnel:
  ```powershell
  ssh -L 8000:localhost:8000 enzo@192.168.50.1
  ```
  Depois abra `http://localhost:8000` no navegador do PC.

### 3.5 Fazer um ensaio

Protocolo padrão (todo ensaio parte do mesmo ponto, para as curvas serem comparáveis):

1. **Malha aberta:** duty `20` → **Aplicar duty**. Espere ~3 s (o motor estabiliza em ~11 RPM).
2. **PID:** Setpoint `40`, Kp, Ki e Kd do ensaio → **Iniciar / atualizar PID**.
   Observe por ~8 s.
3. **Malha aberta:** duty `20` → **Aplicar duty**. Isso fecha o CSV do ensaio.
   Vá para o próximo.
4. No fim: **PARAR** e **Ctrl+C** no terminal.

Regras importantes:
- **Setpoint de até ~55 RPM.** Com `DUTY_MAX = 50 %` a velocidade máxima é de
  ~67 RPM. Acima disso o duty trava em 50 % e os ganhos não fazem diferença.
- Partir de 20 % (e não do motor parado) evita a zona morta do motor (abaixo de
  ~15 % de duty ele não gira).
- Cada conjunto de ganhos gera **um CSV próprio** em `pid/dados/`, com os ganhos
  no nome, por exemplo `pid_20261120_101500_kp1.5_ki7.5_kd0.csv`. Mudar só o
  setpoint continua no mesmo arquivo.

### 3.6 Roteiro de ganhos

Previsão por simulação em
[`pid/analise/resultados/roteiro_ganhos.txt`](pid/analise/resultados/roteiro_ganhos.txt).

| Ens. | Kp | Ki | Kd | Comportamento esperado |
|---|---|---|---|---|
| A1 | 0.3 | 0 | 0 | Lento, para longe do setpoint (erro de ~18 RPM) |
| A2 | 1.0 | 0 | 0 | Mais rápido, erro menor (~9 RPM) |
| A3 | 3.0 | 0 | 0 | Overshoot pequeno, ainda com erro, duty ruidoso |
| A4 | 8.0 | 0 | 0 | Oscilação sustentada |
| B1 | 1.5 | 1 | 0 | Sem overshoot, chega devagar (~3 s) |
| B2 | 1.5 | 3 | 0 | Sem overshoot, ~1 s |
| B3 | 1.5 | 7.5 | 0 | **Referência (Ziegler–Nichols):** rápido e sem overshoot |
| B4 | 1.5 | 15 | 0 | Overshoot de ~9 % |
| B5 | 1.5 | 25 | 0 | Oscilação que demora a sumir |
| B6 | 1.5 | 40 | 0 | Oscilação sustentada |
| C1 | 0.3 | 7.5 | 0 | Overshoot grande (~30 %) e lento |
| C2 | 0.7 | 7.5 | 0 | Overshoot médio (~17 %) |
| C3 | 3.0 | 7.5 | 0 | Oscila, duty muito ruidoso |
| D1 | 1.5 | 7.5 | 0.02 | Quase igual ao B3 |
| D2 | 1.5 | 7.5 | 0.05 | Duty um pouco mais ruidoso |
| D3 | 1.5 | 7.5 | 0.1 | A derivada amplifica o ruído |
| D4 | 1.5 | 7.5 | 0.2 | Overshoot e duty muito ruidoso |

A4, B6 e C3 fazem o duty bater entre 0 e 50 %. Se houver vibração forte, aperte
**Esc**. Para testar rejeição de perturbação, segure o eixo com o PID em regime.

### 3.7 Anotar e salvar os ensaios

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

Para ensaios de malha aberta gravados **antes** de `SINAL_ENCODER = -1` (velocidade
negativa), use `--inverter-sinal`. Para ignorar o trecho com perturbação, use
`--ate <tempo>`. O relatório `.txt` (e os gráficos, se o matplotlib estiver
instalado) vão para `pid/analise/resultados/`.

---

## 5. Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| Navegador: "site can't be reached" / `raspberrypi.local` não encontrado | O nome da Pi é `RASP4`, e não `raspberrypi` | Use `localhost:8000` na Pi, ou o túnel SSH no PC |
| Nada responde na porta 8000 | O `painel.py` não está rodando, ou fechou com erro | Rode `python3 painel.py` e leia a mensagem no terminal |
| Painel não inicia (erro de GPIO) | Outro script está usando os GPIO | `pgrep -af python` e encerre o outro script |
| "Velocidade negativa no modo PID" | Sinal do encoder invertido | `SINAL_ENCODER` em `controle_antigo/hardware.py` |
| Duty travado em 50 % e todas as curvas iguais | Setpoint inalcançável | Use setpoint ≤ ~55 RPM |
| `Could not resolve host: github.com` na Pi | A Pi está sem internet | Normal: use `git push pi main` / `git pull pi main` pelo PC |
| `fatal: not a git repository` | Comando rodado fora da pasta do projeto | `cd` para a pasta do clone |
| `GH007: Your push would publish a private email address` | Commit com e-mail pessoal | Configure o e-mail noreply (seção 2.2) e corrija o commit com `git commit --amend --reset-author --no-edit` |
| `403` / `Permission denied` no push | Login sem permissão de escrita | `gh auth refresh -h github.com -s repo` e `gh auth setup-git` |
| `divergent branches` no pull | Commits diferentes no PC e na Pi | `git pull --no-rebase pi main` (gera um merge) |
| Commit com hora errada no GitHub | Relógio da Pi atrasado | Acerte a hora (seção 3.2) antes dos ensaios |

---

## 6. Fluxo de trabalho do grupo

- Mensagens de commit em português, no imperativo (`Adiciona ...`, `Corrige ...`).
- Ensaios (CSVs) vão para `pid/dados/` **sempre**, inclusive os que deram errado,
  com uma observação no cabeçalho dizendo o que aconteceu.
- Antes de mudar código: `python -m unittest discover -s pid/testes` no PC.
- Mudanças de código devem ser feitas no PC e enviadas para a Pi com `git push pi main`.
  **Não edite o código direto na Pi.** Isso cria versões divergentes que depois
  precisam ser juntadas à mão.
- A `v0` (`controle_antigo/`) recebe correções diretas por enquanto. A `v1`
  (estrutura em `pid/`) vem depois. O estado original da v0 está no commit `c7e9ecc`.
