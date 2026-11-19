# Controle Digital — Trabalho prático

Trabalho em grupo da disciplina **Controle Digital** (Engenharia da Computação).

## Frentes

| Pasta | Conteúdo |
|---|---|
| [`pid/`](pid/) | Controlador PID digital de velocidade (RPM) de um motor DC na Raspberry Pi 4 (Python, ponte H L298N, motor JGA25-370-CE com encoder) |
| [`ssh-bluetooth/`](ssh-bluetooth/) | Acesso SSH à Pi via rede Bluetooth a partir do Windows 11 |
| [`docs/`](docs/) | Referências bibliográficas e relatório |

Contexto completo, hardware, regras de engenharia e fluxo Git: ver [`CLAUDE.md`](CLAUDE.md).

## Como rodar

_A preencher quando o código do PID existir (dependências, comando de execução, testes no PC)._

## Fluxo de trabalho

- Nada de commit direto na `main`: uma branch por tarefa (`pid/...`, `ssh/...`, `docs/...`).
- Toda mudança entra por Pull Request, dizendo como foi testada.
- Antes do PR: `git pull --rebase origin main` e rodar os testes de `pid/testes/`.
