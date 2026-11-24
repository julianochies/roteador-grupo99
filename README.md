# Roteador de estado de enlace sobre UDP

Implementação do trabalho final: cada processo é um roteador inspirado no OSPF.
Ele descobre vizinhos com HELLO, inunda LSPs, monta a LSDB e calcula a tabela
com Dijkstra. Por cima disso encaminha mensagens de texto e um ICMP mínimo
(eco, tempo excedido, destino inalcançável).

O protocolo fica em `roteador/nucleo.py` e não abre socket. `roteador/udp.py`
é a casca: um socket UDP, uma thread de recepção, uma de temporizador e o
terminal. Os testes chamam o núcleo com um relógio falso, então 90 s de
envelhecimento não esperam 90 s.

## Requisitos

Python 3.10 ou superior. Só a biblioteca padrão: `socket`, `threading`,
`heapq` e `unittest`. Não há `requirements.txt`.

## Executar

Na pasta do projeto:

```text
python -m roteador config/r1.txt
```

`config/r1.txt` … `config/r5.txt` são a topologia de referência, todos em
`127.0.0.1` com portas 6001–6005. Para subir os cinco de uma vez, cada um
num console:

```text
python ferramentas/subir_topologia.py
```

Na rede real, copie `config/exemplo_rede_real.txt`, coloque o IP que o
`ipconfig` (Windows) ou o `ip a` (Linux) mostrar e libere a porta UDP no
firewall. No Windows, uma regra de entrada para a porta do roteador. A porta
padrão do enunciado é 6000; nos exemplos locais ela começa em 6001 para
caberem vários roteadores na mesma máquina.

## Arquivo de configuração

Uma linha por vizinho. Linha vazia e linha começando com `#` são ignoradas.
Qualquer outra linha inválida encerra o programa e diz o número da linha.

```text
# Roteador 1 do grupo 99
endereco 10.99.1.1
porta 6001
# vizinho <IP real> <porta UDP> <custo>
vizinho 127.0.0.1 6002 1
vizinho 127.0.0.1 6004 5
```

- `endereco` é `10.G.R.1`, com G e R entre 1 e 254.
- `porta` é opcional e vale 6000 se faltar.
- `custo` é inteiro positivo. Os dois lados do enlace configuram o mesmo custo.
- O IP pode ser nome de máquina; ele é resolvido uma vez, na subida.
- O endereço virtual do vizinho não vai no arquivo. Ele chega no HELLO.

Gerar de novo a topologia de referência (ou outra):

```text
python ferramentas/gerar_topologia.py "1-2:1,2-3:2,1-4:5,3-4:1,3-5:3,4-5:1" --grupo 99 --porta-base 6001
```

## Comandos

| Comando | O que faz |
| --- | --- |
| `tabela` | rede (`10.G.R.0/24`), próximo salto e custo |
| `lsdb` | origem, número de sequência, vizinhos e custos |
| `vizinhos` | configurados, com estado ativo, inativo ou cortado |
| `dijkstra` | tabela de iterações da LSDB atual (para o relatório) |
| `msg <destino> <texto>` | datagrama de texto. ASCII, sem `:` e sem acento |
| `ping <destino> [ttl]` | eco. TTL padrão 16. Mostra quem respondeu e o RTT, ou `timeout` em 2 s |
| `enlace off\|on <virtual>` | corta ou religa um enlace sem matar o processo |
| `silencio` | logs só no arquivo |
| `ajuda` | lista os comandos |
| `sair` | encerra |

`<destino>` é um endereço virtual. `10.99.1.1` e `10.99.1.50` são os dois
atendidos pelo roteador `10.99.1.1`: a rede é a `10.99.1.0/24`.

## O que o log registra

Arquivo `logs/10.99.1.1.log` e o mesmo texto no terminal, com horário e
campos `chave=valor`. Entram vizinho ativo/inativo, LSP gerado, LSP novo,
cópia descartada, LSP expirado, recálculo (com o que mudou e o tempo),
pacote encaminhado (próximo salto e TTL) e ICMP gerado.

`python ferramentas/analisar_logs.py logs` conta esses eventos. Se
`logs/controle.log` tiver um `derrubar` feito pelo `subir_topologia.py`,
o script mede o intervalo até o `ROTAS-RECALCULADAS` de cada roteador.

## Temporizadores

| O quê | Quando |
| --- | --- |
| HELLO | a cada 5 s, para todo vizinho configurado, ativo ou não |
| Vizinho inativo | 20 s sem HELLO |
| LSP próprio | ao subir, quando um vizinho entra ou sai, e a cada 30 s |
| LSP alheio some | 90 s sem renovação. O LSP próprio não envelhece |
| Ping | timeout em 2 s |

O primeiro número de sequência é o horário Unix na hora em que o processo
sobe. Cada LSP nosso soma 1. Reenviar o LSP de outro roteador não muda o
número: a cópia é o mesmo texto, byte a byte.

Há uma decisão a mais, para o reinício rápido. Se o vizinho direto manda um
LSP com sequência que pula mais de 1 (o processo voltou e o Unix time está
à frente), devolvemos a LSDB inteira para ele. Renovação normal é sempre
+1, então a contagem da inundação não muda. Sem isso, um roteador derrubado
e religado em menos de 20 s ficaria sem a topologia até a renovação de 30 s,
porque para o vizinho ele nunca chegou a cair.

## Opções de teste

Não mudam o formato dos pacotes.

```text
python -m roteador config/r1.txt --escala-tempo 0.1
python -m roteador config/r1.txt --perda-lsp 0.3 --semente 1
python -m roteador config/r1.txt --perder-proximo-lsp-de 10.99.2.1
```

- `--escala-tempo 0.1` faz o tempo virtual andar 10 vezes mais rápido.
- `--perda-lsp` descarta essa fração dos LSPs recebidos.
- `--perder-proximo-lsp-de` descarta só o próximo LSP daquela origem.
  Serve para a questão 5 (LSDB desatualizada até a renovação) e, com o
  enlace cortado, para o laço da questão 6.

Pacote cru, inclusive malformado, saindo da porta de um vizinho:

```text
python ferramentas/injetor.py 127.0.0.1 6001 --de-porta 6002 "LSP:10.99.9.1:1:."
```

De um par `(IP, porta)` que não está na configuração, o pacote é descartado
antes do parse.

## Testes

```text
python -m unittest discover -s tests -t .
```

A suíte cobre o formato do enunciado, vizinhança, sequência e inundação
(na topologia de referência: 4 LSPs aceitos e 4 cópias por inundação),
o gabarito do Dijkstra, entrega, TTL, ICMP e dois processos UDP de verdade
em `127.0.0.1`.

## Topologia de referência

Enlaces: R1–R2 = 1, R2–R3 = 2, R1–R4 = 5, R3–R4 = 1, R3–R5 = 3, R4–R5 = 1.
Rn é `10.99.n.1`.

Tabela de R1 (próximo salto / custo):

| Destino | Normal | Sem R2 | Sem R3 | Sem R4 |
| --- | --- | --- | --- | --- |
| R2 | R2 / 1 | sem rota | R2 / 1 | R2 / 1 |
| R3 | R2 / 3 | R4 / 6 | sem rota | R2 / 3 |
| R4 | R2 / 4 | R4 / 5 | R4 / 5 | sem rota |
| R5 | R2 / 5 | R4 / 6 | R4 / 6 | R2 / 6 |

R1 chega em R4 por R2–R3–R4 (custo 4), não pelo enlace direto (custo 5).
O Dijkstra soma custo; não conta saltos. Empate de custo fica com o próximo
salto de menor endereço, comparado octeto a octeto.

## Onde está cada regra

| Arquivo | Responsabilidade |
| --- | --- |
| `pacotes.py` | HELLO, LSP, DADOS, ICMP. ASCII, campos separados por `:` |
| `vizinhos.py` | ativo/inativo e o par (IP, porta) aprendido no HELLO |
| `lsdb.py` | um LSP por origem; expira o alheio em 90 s |
| `dijkstra.py` | tabela e a tabela de iterações, com `heapq` |
| `nucleo.py` | inundação, encaminhamento, ICMP, comandos |
| `udp.py` | o socket único e as threads |

No Windows, `recvfrom` pode levantar `ConnectionResetError` quando o vizinho
está desligado (ICMP de porta inalcançável). O laço captura e continua.

## Limite do número de sequência

Se o roteador gerar LSPs mais depressa do que o relógio avança e for
reiniciado no mesmo segundo, o seq novo pode ser menor que o que os outros
guardam. Esses LSPs são descartados até o antigo envelhecer (90 s). É o
comportamento do enunciado: o primeiro seq é o horário, e não há memória
do número anterior.
