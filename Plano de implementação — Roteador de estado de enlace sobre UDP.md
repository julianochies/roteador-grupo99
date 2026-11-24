# Plano de implementação — Roteador de estado de enlace sobre UDP

Nov 24, 2026 · @Juliano

## 1. Visão geral e decisões de arquitetura

A proposta é implementar o roteador em **Python 3, só com a biblioteca padrão**, separando um **núcleo de protocolo sem I/O** (que decide tudo) de uma **casca fina** (socket, relógio, terminal). Essa separação é o que torna o roteador testável em segundos, sem esperar temporizadores reais, e fácil de explicar linha a linha na apresentação.

**Por que Python:** funciona nos dois ambientes (VDI exige Python; no access point qualquer linguagem serve), tem `socket`, `threading`, `heapq` e `unittest` prontos, e o código fica curto o bastante para todos os integrantes dominarem.

**Decisões que valem para todo o projeto:**

- **Um único socket UDP** ligado em `0.0.0.0:<porta>`, usado para enviar e receber. Assim a porta de origem de tudo que sai é a porta do roteador, como a especificação exige.
- **Três threads:** recepção (bloqueia em `recvfrom`), temporizador (acorda a cada 0,5 s) e terminal (lê comandos). Todas chamam o núcleo protegido por **um único lock**, o que elimina condições de corrida sem complicar o código.
- **Núcleo determinístico:** o núcleo recebe o horário atual como parâmetro (`now`) e devolve uma lista de pacotes a enviar e de eventos de log. Não chama `time.time()` nem `sendto()` diretamente.
- **Seguir o formato à risca:** o parser é estrito no que aceita como válido (campos, tipos, ASCII, sem `:` na mensagem) e só tolera `\r\n` no final, para conversar com qualquer outro grupo.
- **Sem bibliotecas de grafos:** Dijkstra escrito pelo grupo com `heapq`, que é permitido.
- **Desempate determinístico no Dijkstra** (menor endereço virtual do próximo salto), para que os testes e a demonstração sempre deem o mesmo resultado.
- **Código simples e comentado em português**, com cada regra apontando para a seção do enunciado. Isso protege o grupo na regra sobre uso de IA: ninguém deve ter no código algo que não saiba explicar.

Os pesos da avaliação orientam a prioridade: LSPs e inundação (20%), relatório (20%), Dijkstra (15%) e ICMP (15%) somam 70% da nota.

## 2. Estrutura do projeto

Cada arquivo tem uma responsabilidade única e pode ser testado isoladamente; só `udp.py`, `relogio.py`, `cli.py` e `main.py` tocam o mundo real.

```
roteador/
  main.py          # ponto de entrada: python -m roteador config/r1.txt
  config.py        # leitura e validação do arquivo de configuração
  pacotes.py       # parse e serialização de HELLO, LSP, DADOS, ICMP
  enderecos.py     # validação de 10.G.R.x, rede_de(endereco)
  vizinhos.py      # tabela de vizinhos: ativo/inativo, (IP, porta) <-> virtual
  lsdb.py          # LSDB: inserção por número de sequência, envelhecimento
  dijkstra.py      # função pura: LSDB -> tabela de roteamento
  nucleo.py        # RoteadorNucleo: todas as regras do protocolo, sem I/O
  udp.py           # socket UDP real + threads de recepção e temporizador
  relogio.py       # RelogioReal e RelogioFalso (para testes)
  cli.py           # comandos tabela, lsdb, vizinhos, msg, ping
  log.py           # logs em arquivo e terminal, formato chave=valor
tests/
  test_pacotes.py  test_dijkstra.py  test_lsdb.py  test_vizinhos.py
  test_encaminhamento.py  test_icmp.py  test_cenarios.py  test_udp_real.py
ferramentas/
  gerar_topologia.py   # gera configs de N roteadores em localhost
  subir_topologia.py   # inicia/derruba roteadores locais
  injetor.py           # envia pacotes UDP crus (malformados, falsos)
  analisar_logs.py     # conta LSPs e mede convergência a partir dos logs
config/                # exemplos: r1.txt ... r5.txt, grupo.txt
README.md
```

| Módulo | Entrada | Saída | Depende de |
| --- | --- | --- | --- |
| `pacotes.py` | bytes recebidos | objeto `Hello`, `Lsp`, `Dados` ou `Icmp`, ou exceção `PacoteMalformado` | nada |
| `vizinhos.py` | HELLO recebido, `now` | mudanças (entrou / saiu) | `config` |
| `lsdb.py` | LSP, `now` | aceito ou descartado; LSPs expirados | nada |
| `dijkstra.py` | LSDB, endereço próprio | tabela `{rede: (próximo salto, custo)}` | nada |
| `nucleo.py` | evento (pacote, tick, comando) + `now` | lista de envios `(bytes, (ip, porta))` + eventos de log | todos acima |
| `udp.py` / `cli.py` | socket, teclado | chamadas ao núcleo | `nucleo` |

O diagrama da arquitetura (threads, núcleo e socket) está no fim desta seção.

&#91;embedded content: arquitetura · 3 threads, 1 núcleo, 1 socket\]

As três threads só entregam eventos ao núcleo; o núcleo devolve envios, eventos de log e mensagens, e é a única parte com regras do protocolo. Nos testes, as threads e o socket são trocados pela rede simulada e pelo relógio falso.

## 3. Arquivo de configuração

Formato proposto: texto simples, **uma linha por vizinho**, porque na interoperabilidade o enunciado pede exatamente "uma linha a mais no arquivo de configuração" e porque o IP real muda a cada conexão (DHCP).

```
# Roteador 1 do grupo 7
endereco 10.7.1.1
porta 6000
# vizinho <IP real> <porta UDP> <custo>
vizinho 192.168.0.11 6000 1
vizinho 192.168.0.12 6000 5
# enlace com o outro grupo (só na interoperabilidade)
# vizinho 192.168.0.31 6000 2
```

Regras de leitura em `config.py`:

- Linhas vazias e iniciadas por `#` são ignoradas. Qualquer outra linha inválida encerra o programa com mensagem clara (número da linha e motivo).
- `endereco` precisa ter a forma `10.G.R.1`, com G e R entre 1 e 254 e o último octeto igual a 1.
- `porta` é opcional, padrão 6000.
- `custo` é inteiro positivo; zero, negativo ou texto são erro.
- O IP pode ser nome de máquina; ele é convertido com `socket.gethostbyname` uma vez, para que a comparação com o `(ip, porta)` de quem enviou o pacote funcione.
- Vizinho repetido (mesmo IP e porta) é erro.

O arquivo **não** traz o endereço virtual do vizinho: ele é aprendido pelo HELLO. Por isso o custo fica associado ao par `(ip, porta)` e, quando o HELLO chega, o roteador passa a saber que `10.7.2.1` tem custo 1.

Para testes em uma máquina só, todos os vizinhos usam `127.0.0.1` com portas diferentes (6001, 6002...). O script `gerar_topologia.py` produz esses arquivos a partir de uma lista de enlaces como `1-2:1, 2-3:2, 1-4:5`.

## 4. Implementação por componente

A ordem abaixo é a ordem de construção: cada componente só depende dos anteriores e já nasce com seus testes.

### 4.1 Pacotes (`pacotes.py`)

- `parse(bytes) -> Hello | Lsp | Dados | Icmp`; qualquer problema levanta `PacoteMalformado(motivo)`.
- Decodificar com `data.decode('ascii')` (erro de decodificação = malformado) e remover só `\r\n` final.
- Separar por `:` e conferir o número **exato** de campos: HELLO 2, LSP 4, DADOS 6, ICMP 6. Como a mensagem não pode ter `:`, um DADOS com `:` no texto tem mais de 6 campos e cai aqui naturalmente.
- Validar endereços virtuais (4 octetos 0–255, primeiro octeto 10), TTL e id inteiros, tipo ICMP em {0, 3, 8, 11}, custos inteiros positivos.
- Lista do LSP: `.` significa vazia; senão, itens `vizinho=custo` separados por `;`.
- Serialização é o inverso exato, sem `\n` no final. Teste obrigatório: `parse(serializa(p)) == p` para todos os tipos.

### 4.2 Vizinhança (`vizinhos.py`)

Estado por vizinho configurado: `ip`, `porta`, `custo`, `virtual` (ou `None`), `ultimo_hello`, `ativo`.

- A cada 5 s, enviar `HELLO:<próprio>` para **todos os configurados**, ativos ou não.
- HELLO recebido de `(ip, porta)` configurado: grava `virtual` e `ultimo_hello = now`. Se estava inativo, vira ativo e devolve o evento `ENTROU`. Se o virtual mudou para o mesmo par, trata como saída + entrada.
- No tick: vizinho ativo com `now - ultimo_hello >= 20` vira inativo e devolve `SAIU`.
- Qualquer `ENTROU`/`SAIU` dispara, no núcleo, um novo LSP próprio **imediatamente**.

### 4.3 LSP, inundação e LSDB (`lsdb.py` + `nucleo.py`)

Geração do LSP próprio:

- `seq` começa em `int(time.time())` no início do programa; cada novo LSP faz `seq += 1`.
- Conteúdo: vizinhos **ativos** com o custo configurado; sem vizinhos, lista `.`.
- Gerar quando um vizinho entra ou sai e a cada 30 s. Gravar na própria LSDB e enviar a todos os vizinhos ativos.

Recebimento de LSP vindo do vizinho V (pseudocódigo):

```
se lsp.origem == eu: descartar (log LSP-PROPRIO)
atual = lsdb.get(lsp.origem)
se atual e atual.seq >= lsp.seq: descartar (log LSP-DUPLICADO)
lsdb[lsp.origem] = (lsp, recebido_em=now)
enviar cópia idêntica a todos os vizinhos ativos, exceto V
recalcular tabela
```

- Sincronização: quando um vizinho fica ativo, enviar a ele o novo LSP próprio **e** todas as entradas da LSDB.
- Envelhecimento: no tick, remover LSPs de outros roteadores com `now - recebido_em >= 90` e recalcular. O LSP próprio nunca envelhece.
- Ponto a decidir e registrar no README: aceitar LSP de vizinho configurado que ainda não mandou HELLO. Recomendação: aceitar (o par `(ip, porta)` é conhecido), porque o HELLO e o LSP podem chegar fora de ordem.

### 4.4 Tabela de roteamento (`dijkstra.py`)

- Grafo dirigido: para cada LSP de origem O, arestas O → vizinho com o custo listado. Um destino que aparece só como vizinho de alguém (sem LSP próprio) é alcançável, mas não é expandido.
- Dijkstra com `heapq` a partir do próprio roteador, guardando para cada nó `(custo, primeiro_salto)`. O primeiro salto de um vizinho direto é ele mesmo; dos demais, herda do predecessor.
- Desempate: com custo igual, fica o primeiro salto de menor endereço.
- Saída: `{"10.G.R": (proximo_salto, custo)}` para cada roteador alcançável, exceto o próprio. A chave é o prefixo de 3 octetos, que representa a rede `/24`.
- Função separada `dijkstra_passos(...)` devolve a tabela de iterações (conjunto N', D(v), p(v)) para o relatório e para a pergunta "mostre o Dijkstra".
- Recalcular sempre que a LSDB muda; registrar no log as rotas que mudaram (diferença entre a tabela antiga e a nova) e o tempo gasto.

### 4.5 Encaminhamento e ICMP (`nucleo.py`)

Ao **originar** (comandos `msg` e `ping`, e mensagens de erro geradas): procurar `rede_de(destino)` na tabela; sem rota, avisar o usuário e não enviar; com rota, enviar ao `(ip, porta)` do próximo salto com TTL 16 (ou o do `ping`).

Ao **receber** DADOS ou ICMP, na ordem exata do enunciado:

1. `rede_de(destino) == rede_de(eu)` → entregar: DADOS exibe origem, destino e texto; ICMP 8 responde com tipo 0, **origem = destino do pedido**, mesmo id, TTL 16; ICMP 0, 3 e 11 são entregues ao `ping` pendente com aquele id.
2. Senão, `ttl -= 1`. Se `ttl <= 0`: descartar e gerar ICMP 11 para a origem.
3. Senão, sem rota: descartar e gerar ICMP 3 para a origem.
4. Senão, encaminhar com o novo TTL e registrar no log o próximo salto e o TTL.

Mensagens de erro: origem = endereço do próprio roteador, TTL 16, id do pacote que causou o erro. **Nunca** gerar 11 ou 3 em resposta a um ICMP 11 ou 3 (mas pedido e resposta de eco, tipos 8 e 0, geram erros normalmente). Se o próprio erro não tiver rota, só registrar no log.

O fluxo completo está desenhado no fim desta seção.

&#91;embedded content: recebimento de DADOS e ICMP · 3 decisões, 4 saídas\]

A ordem das decisões é a do enunciado: entrega local antes de mexer no TTL, depois TTL, depois rota. Cada saída vira um teste (E1, I1, I3, E2) e uma linha no log.

### 4.6 Ping e terminal (`cli.py`)

- Comandos obrigatórios: `tabela`, `lsdb`, `vizinhos`, `msg <destino> <texto>`, `ping <destino> [TTL]`. Extras úteis: `ajuda`, `sair`.
- Validar antes de enviar: destino é endereço virtual; texto ASCII sem `:`; TTL inteiro entre 1 e 255.
- `ping`: escolhe `id` de um contador próprio, guarda `pendentes[id] = (destino, t_envio)` e retorna o prompt. A resposta (0, 11 ou 3) com aquele id imprime tipo, quem enviou e o RTT em ms; o tick remove pendentes com mais de 2 s e imprime `timeout`.
- Ping para o próprio endereço ou para um endereço da própria rede (ex.: `10.7.1.50`) é atendido localmente.
- Saída alinhada em colunas, para comparar fácil com a topologia.

### 4.7 Logs (`log.py`)

Um arquivo por roteador (`logs/10.7.1.1.log`) e cópia no terminal, com horário em milissegundos e formato `chave=valor` para que o `analisar_logs.py` consiga contar e medir.

| Evento | Exemplo de linha |
| --- | --- |
| Vizinho ativo / inativo | `12:00:01.250 VIZINHO-ATIVO viz=10.7.2.1 end=192.168.0.11:6000` |
| LSP gerado | `LSP-GERADO seq=1767712003 viz=10.7.2.1=1;10.7.4.1=5 motivo=vizinho-saiu` |
| LSP novo recebido | `LSP-NOVO origem=10.7.3.1 seq=1767711990 de=10.7.2.1 reenviado=2` |
| LSP descartado | `LSP-DUPLICADO origem=10.7.3.1 seq=1767711990 de=10.7.4.1` |
| LSP envelhecido | `LSP-EXPIRADO origem=10.7.5.1 idade=90.2s` |
| Recálculo | `ROTAS-RECALCULADAS mudou=10.7.3:10.7.2.1/3->10.7.4.1/6 tempo=0.4ms` |
| Encaminhamento | `ENCAMINHADO tipo=ICMP8 origem=10.7.1.1 destino=10.7.3.1 prox=10.7.2.1 ttl=15` |
| ICMP gerado | `ICMP-GERADO tipo=11 para=10.7.1.1 id=42` |
| Pacote descartado | `DESCARTADO motivo=malformado de=192.168.0.99:5000` |

Os logs de LSP-DUPLICADO e DESCARTADO não são exigidos, mas são eles que respondem "quantos foram descartados como cópias" no relatório.

## 5. Concorrência, temporizadores e casos de borda

Todos os temporizadores são verificados em um único `tick(now)` do núcleo, chamado a cada 0,5 s; nenhum temporizador tem thread própria.

| Temporizador | Valor | Verificação no `tick` |
| --- | --- | --- |
| Envio de HELLO | 5 s | `now >= proximo_hello` |
| Vizinho inativo | 20 s sem HELLO | `now - ultimo_hello >= 20` |
| Renovação do LSP próprio | 30 s | `now >= proxima_renovacao` |
| Envelhecimento de LSP alheio | 90 s | `now - recebido_em >= 90` |
| Timeout do ping | 2 s | `now - t_envio >= 2` |

Casos de borda que precisam de tratamento explícito:

- **Windows e UDP:** o `recvfrom` pode levantar `ConnectionResetError` (erro 10054) quando um vizinho está desligado e a máquina recebe ICMP "porta inalcançável". Capturar e continuar o laço; senão a thread de recepção morre e o roteador para de funcionar sem aviso.
- **Exceção no processamento:** o laço de recepção tem `try/except` geral que registra `DESCARTADO motivo=erro-interno` e segue. Um pacote nunca derruba o roteador.
- **Remetente desconhecido:** `(ip, porta)` fora da configuração é descartado antes do parse.
- **Relógio:** usar `time.monotonic()` para os temporizadores (imune a ajuste de hora) e `time.time()` só para o primeiro número de sequência e para o horário dos logs.
- **Terminal e logs no mesmo terminal:** as linhas de log podem cortar o que se está digitando. Solução simples: reimprimir o prompt ` >  ` depois de cada log; opcionalmente um comando `silencio` que deixa os logs só no arquivo durante a demonstração.
- **Encerramento:** `sair` ou Ctrl+C fecham o socket e terminam as threads (marcadas como `daemon`).
- **Reinício rápido:** se o roteador gerou mais LSPs do que segundos se passaram desde que iniciou e for reiniciado logo em seguida, o novo `seq` (horário atual) pode ser menor que o antigo e seus LSPs serão descartados até o antigo envelhecer (90 s). É um limite da especificação, não um bug: saber explicar isso responde à questão 4 do relatório.

## 6. Testabilidade

A implementação é testável porque **todo o protocolo roda sem rede e sem esperar**: o núcleo recebe o horário e devolve o que enviaria, então 90 s de envelhecimento são testados em milissegundos com um relógio falso. Isso permite provar cada regra do enunciado com um teste e responder a qualquer "e se...?" do professor rodando um cenário na hora.

### 6.1 Decisões de projeto que habilitam os testes

- **Núcleo puro:** `RoteadorNucleo.receber(dados, remetente, now)`, `.tick(now)` e `.comando(texto, now)` devolvem `Saida(envios=[(bytes, (ip, porta))], eventos=[...], mensagens_usuario=[...])`. Nada é impresso nem enviado de dentro do núcleo.
- **Relógio injetável:** `RelogioReal` em produção, `RelogioFalso.avancar(segundos)` nos testes.
- **Rede simulada:** `RedeSimulada` instancia N núcleos, entrega os envios de um como recebimentos do outro e permite `derrubar(r)`, `religar(r)`, `cortar_enlace(a, b)` e `perda(probabilidade, semente)`.
- **Determinismo:** desempate fixo no Dijkstra, ids de ping sequenciais e semente fixa na perda simulada. Um teste que passa uma vez passa sempre.
- **Eventos estruturados:** cada evento de log é um objeto (`tipo`, campos) antes de virar texto. Os testes verificam eventos, não strings.
- **Opções só para teste**, desligadas por padrão e documentadas no README: `--escala-tempo 0.1` (temporizadores 10× mais rápidos nos testes com UDP real), `--perda-lsp 0.3` (descarta 30% dos LSPs recebidos, para a questão 5) e o comando `enlace off|on <virtual>` (para de enviar HELLO e ignora pacotes daquele vizinho, simulando um enlace cortado sem matar o processo). Nenhuma delas muda o formato dos pacotes.

Exemplo de teste de cenário, que roda em menos de 1 s:

```python
def test_reconvergencia_apos_queda_de_r2(self):
    rede = RedeSimulada.da_topologia("1-2:1,2-3:2,1-4:5,3-4:1,3-5:3,4-5:1", grupo=7)
    rede.rodar(segundos=10)                       # HELLOs, LSPs e sincronização
    self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.2.1", 3))
    rede.derrubar(2)
    rede.rodar(segundos=21)                       # passa os 20 s de detecção
    self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.4.1", 6))
    self.assertTrue(rede.eventos(1, "VIZINHO-INATIVO", viz="10.7.2.1"))
```

### 6.2 Camadas de teste

| Camada | O que cobre | Como roda | Tempo |
| --- | --- | --- | --- |
| Unitário | parser, LSDB, vizinhos, Dijkstra, regras de encaminhamento e ICMP | `python -m unittest discover tests` | < 1 s |
| Cenário simulado | inundação, convergência, queda, reinício, perda de LSP, laço durante convergência | `RedeSimulada` + `RelogioFalso` | < 5 s |
| Integração UDP real | socket único, threads, terminal, logs em arquivo | `test_udp_real.py` sobe 3 processos em 127.0.0.1 com `--escala-tempo 0.1` e conversa pelo stdin | \~ 15 s |
| Topologia local completa | os 5 roteadores do relatório, Wireshark na interface de loopback | `ferramentas/subir_topologia.py` | manual |
| Rede real do grupo | IPs reais, firewall, DHCP | um roteador por máquina | ensaio geral |
| Interoperabilidade | outro grupo, formatos exatos | `injetor.py` + ensaio com outro grupo | ensaio geral |

### 6.3 Topologia de referência com resultados esperados

Cinco roteadores, seis enlaces e caminhos alternativos (atende ao mínimo do relatório). Os valores abaixo foram calculados com Dijkstra e servem de **gabarito** nos testes e na demonstração. R*n* = `10.G.n.1`.

Enlaces: R1–R2 = 1, R2–R3 = 2, R1–R4 = 5, R3–R4 = 1, R3–R5 = 3, R4–R5 = 1.

&#91;embedded content: topologia de referência · 5 roteadores, 6 enlaces\]

Os números são os custos. A mesma figura entra no relatório; o grupo de 4 na apresentação pode usar R1–R4 com os mesmos custos, que ainda tem caminho alternativo.

Tabela esperada de R1 (próximo salto / custo):

| Destino | Normal | Sem R2 | Sem R3 | Sem R4 |
| --- | --- | --- | --- | --- |
| R2 | R2 / 1 | sem rota | R2 / 1 | R2 / 1 |
| R3 | R2 / 3 | R4 / 6 | sem rota | R2 / 3 |
| R4 | R2 / 4 | R4 / 5 | R4 / 5 | sem rota |
| R5 | R2 / 5 | R4 / 6 | R4 / 6 | R2 / 6 |

Tabela esperada de R5: R1 via R4 / 5, R2 via R4 / 4, R3 via R4 / 2, R4 via R4 / 1. Repare que R4 é alcançado por R1 pelo caminho R1–R2–R3–R4 (custo 4) e não pelo enlace direto (custo 5): é o exemplo ideal para mostrar que o Dijkstra soma custos e não conta saltos.

### 6.4 Matriz de casos de teste por critério de avaliação

| ID | Critério | Cenário | Resultado esperado |
| --- | --- | --- | --- |
| V1 | Vizinhança | Avançar 5 s | Um HELLO para cada vizinho configurado, ativo ou não |
| V2 | Vizinhança | Primeiro HELLO de um vizinho | Vizinho ativo, virtual associado ao `(ip, porta)`, LSP gerado na hora |
| V3 | Vizinhança | 19,5 s e depois 20 s sem HELLO | Ativo aos 19,5 s; inativo aos 20 s e novo LSP |
| V4 | Vizinhança | HELLO de `(ip, porta)` fora da configuração | Descartado, nada muda |
| V5 | Vizinhança | Vizinho volta após cair | Ativo de novo e recebe LSP próprio + todos os LSPs da LSDB |
| L1 | LSPs | Iniciar e esperar 30 s | `seq` inicial = Unix time; renovação com `seq + 1` |
| L2 | LSPs | LSP com `seq` maior | Substitui, reenvia a todos os ativos exceto o remetente, recalcula |
| L3 | LSPs | Mesmo LSP chega por outro vizinho | Descartado como cópia, não reenviado |
| L4 | LSPs | LSP com `seq` menor | Descartado |
| L5 | LSPs | LSP com origem = próprio roteador | Descartado |
| L6 | LSPs | Reenvio de LSP alheio | Bytes idênticos aos recebidos (mesmo `seq`) |
| L7 | LSPs | LSP alheio sem renovação por 89 s e por 90 s | Presente aos 89 s; removido aos 90 s e tabela recalculada; LSP próprio nunca sai |
| L8 | LSPs | Roteador sem vizinhos ativos | Gera `LSP:<eu>:<seq>:.` |
| L9 | LSPs | Uma mudança na topologia de referência | Cada roteador aceita o LSP uma vez; total de cópias bate com a fórmula da seção 8 |
| L10 | LSPs | Reinício de um roteador | Novo `seq` maior que o antigo; LSPs aceitos pelos demais |
| D1 | Tabela | Topologia de referência | Igual ao gabarito da seção 6.3 |
| D2 | Tabela | Queda de R2, R3 ou R4 | Igual às colunas "Sem Rx" do gabarito |
| D3 | Tabela | Destino listado como vizinho, sem LSP próprio | Rota existe; nó não é expandido |
| D4 | Tabela | Dois caminhos de mesmo custo | Sempre o mesmo próximo salto (menor endereço) |
| D5 | Tabela | Rede particionada | Destinos da outra parte sem rota |
| D6 | Tabela | Cada mudança da LSDB | Exatamente um recálculo registrado |
| E1 | Encaminhamento | DADOS para `10.G.R.1` e para `10.G.R.50` | Ambos entregues e exibidos pelo roteador R |
| E2 | Encaminhamento | DADOS em trânsito | TTL decrementado em 1, enviado ao `(ip, porta)` do próximo salto |
| E3 | Encaminhamento | `msg` para rede sem rota | Aviso ao usuário, nenhum pacote enviado |
| I1 | ICMP | `ping` com TTL 1, 2, 3... até R5 | Tempo excedido vindo de cada roteador do caminho, na ordem; eco no TTL = número de saltos |
| I2 | ICMP | `ping 10.G.R.50` | Resposta tipo 0 com origem `10.G.R.50` e o mesmo id |
| I3 | ICMP | Roteador intermediário sem rota | ICMP 3 com origem = intermediário |
| I4 | ICMP | ICMP 11 ou 3 com TTL esgotado ou sem rota | Descartado sem gerar outro erro |
| I5 | ICMP | Resposta de eco (tipo 0) com TTL esgotado | Gera ICMP 11 normalmente |
| I6 | ICMP | Destino cai depois de a rota existir | `timeout` após 2 s |
| I7 | ICMP | Dois pings simultâneos | Cada resposta associada ao id certo, RTT de cada um |
| P1 | Robustez | Malformados: tipo desconhecido, campos a mais ou a menos, TTL `abc`, custo 0, acento, `:` na mensagem, endereço `10.1.2`, pacote vazio, bytes binários | Todos descartados com log; o roteador continua respondendo a `ping` |
| O1 | Observabilidade | Cada evento da seção 4.7 | Uma linha com horário e os campos esperados, no arquivo e no terminal |
| X1 | Interoperabilidade | Strings exatas dos exemplos do enunciado | Parse aceita e serialização reproduz byte a byte |
| X2 | Interoperabilidade | Dois grupos locais (G=7 e G=8) ligados por um enlace | LSDB com os roteadores dos dois grupos, ping e msg atravessando, reconvergência ao cortar o enlace |

### 6.5 Ferramentas de apoio

- `gerar_topologia.py "1-2:1,2-3:2,..." --grupo 7 --porta-base 6001` gera `config/r1.txt` a `r5.txt` em 127.0.0.1.
- `subir_topologia.py` abre um terminal por roteador (ou roda em segundo plano com logs em arquivo) e aceita `derrubar 3` / `religar 3`, registrando o horário exato da queda para medir convergência.
- `injetor.py 127.0.0.1 6001 --de-porta 6002 "LSP:10.7.9.1:1:."` envia um pacote cru a partir de uma porta escolhida, para testar malformados e simular o outro grupo.
- `analisar_logs.py logs/` conta LSPs enviados, aceitos e duplicados por janela de tempo e mede o intervalo entre `derrubar` e o `ROTAS-RECALCULADAS` de cada roteador.
- Filtros de Wireshark: `udp.port >= 6000 && udp.port <= 6010`, `udp contains "LSP:"`, `udp contains "ICMP:"`.

### 6.6 Checklist de interoperabilidade

- [ ] Pacotes enviados sem `\n` e sem espaços extras; recebidos com `\r\n` final também aceitos.
- [ ] LSP sem vizinhos usa exatamente `.`.
- [ ] Envio e recebimento pelo mesmo socket, na porta configurada.
- [ ] HELLO enviado também para vizinhos ainda inativos.
- [ ] Roteador aceita LSPs de origens de outro grupo (`10.8.x.1`) e cria rota para `10.8.x.0/24`.
- [ ] Firewall liberado para a porta UDP (Windows: regra de entrada; Linux: `ufw allow 6000/udp`).
- [ ] Testado com pelo menos um outro grupo antes da apresentação.

## 7. Preparação para os testes e perguntas do professor

A apresentação tem \~10 min por grupo e o professor pode pedir qualquer variação; o grupo deve chegar com o roteiro abaixo ensaiado e com uma resposta curta para cada pergunta do banco, sabendo apontar a linha do código correspondente.

### 7.1 Roteiro da demonstração

1. **Antes do horário:** rede montada (4 roteadores, custos diferentes, um caminho alternativo), IPs conferidos, firewall liberado, logs limpos.
2. **Vizinhos, LSDB e tabela** em cada roteador, comparando com a figura da topologia impressa ou na tela.
3. **`ping` com TTL 1, 2, 3...** até o roteador mais distante: cada resposta de tempo excedido mostra um roteador do caminho; a última é a resposta de eco. Em seguida, uma `msg`.
4. **`ping` para rede inexistente** (ex.: `10.G.99.1`): "destino inalcançável" local, sem enviar nada.
5. **Queda:** o professor derruba um roteador ou enlace. Mostrar no log o `VIZINHO-INATIVO` (espera de 15 a 20 s), o `LSP-GERADO`, os `LSP-NOVO` nos outros e o `ROTAS-RECALCULADAS`; repetir o ping com TTL crescente e mostrar o novo caminho. Religar o roteador e mostrar a sincronização.
6. **Interoperabilidade:** adicionar a linha do vizinho do outro grupo nos dois lados, reiniciar esses dois roteadores, mostrar `lsdb` e `tabela` com os roteadores do outro grupo, ping com TTL crescente e msg atravessando, e reconvergência quando o enlace entre grupos cair.

### 7.2 Banco de perguntas sobre o código

- **Qual o caminho de um pacote dentro do programa?** Thread de recepção em `udp.py` → filtro de remetente → `pacotes.parse` → `nucleo.receber` → handler do tipo → lista de envios → `sendto` no mesmo socket.
- **Por que um socket só?** Para que a porta de origem seja a porta do roteador; é assim que o vizinho reconhece quem enviou.
- **Como o roteador sabe para onde mandar um pacote para `10.7.3.1`?** `rede_de` dá `10.7.3`; a tabela dá o próximo salto virtual; a tabela de vizinhos dá o `(ip, porta)` aprendido no HELLO.
- **Por que 20 s para inativo se o HELLO é a cada 5 s?** Tolera até 3 HELLOs perdidos seguidos sem declarar queda falsa; o preço é uma detecção de 15 a 20 s.
- **O que impede a inundação de circular para sempre?** O número de sequência: cópia com `seq` igual ou menor é descartada e não é reenviada.
- **Por que não mudar o `seq` ao reenviar?** Ele identifica a versão do LSP do roteador de origem; se cada um mudasse, ninguém reconheceria cópias.
- **Por que o `seq` começa no Unix time?** Um roteador reiniciado não lembra o último número; começando pelo horário, ele sai à frente do que os outros conhecem.
- **Mostre o Dijkstra.** Fila de prioridade com `(custo, nó)`; ao retirar um nó já visitado, ignora (entrada antiga); relaxa as arestas do LSP do nó; o primeiro salto vem do vizinho direto e é herdado. Complexidade O((V + E) log V).
- **Por que a rota de R1 para R4 não usa o enlace direto?** Custo 5 contra 1 + 2 + 1 = 4 pelo outro caminho: menor soma de custos, não menor número de saltos.
- **O LSP do roteador que caiu continua na LSDB. Isso não cria rota errada?** Não: os vizinhos dele geram LSPs sem ele, então nenhuma aresta leva até ele. O LSP dele só sai aos 90 s, por envelhecimento.
- **Por que o TTL é decrementado só quando o destino é outra rede?** É a ordem do enunciado; com isso `ping` com TTL igual ao número de saltos chega ao destino.
- **Por que `ping` com TTL k mostra o k-ésimo roteador?** Cada roteador do caminho tira 1; no k-ésimo o TTL chega a 0 e ele responde com tipo 11 usando o próprio endereço.
- **Por que não gerar erro sobre erro?** Evita cascata de mensagens de erro, inclusive em laços durante a convergência.
- **E se duas threads mexerem na LSDB ao mesmo tempo?** Não acontece: todas as entradas no núcleo passam pelo mesmo lock.
- **E se um lado ver o HELLO e o outro não (enlace unidirecional)?** Só um lado lista o enlace no LSP; o Dijkstra usa a aresta existente, então o tráfego pode ir num sentido e não voltar. O OSPF resolve com verificação bidirecional, que a especificação não exige.
- **E se os dois lados configurarem custos diferentes?** Cada sentido usa o seu custo e as rotas de ida e volta podem divergir; por isso o enunciado exige custos iguais.
- **Por que UDP e não TCP?** É o que se pede, e reflete o protocolo real (OSPF roda direto sobre IP, sem conexão): a confiabilidade vem da renovação periódica, não de confirmação.

### 7.3 Pedidos ao vivo e como atender

| Pedido | Como atender |
| --- | --- |
| Derrubar um roteador | Ctrl+C no terminal dele; religar com o mesmo comando |
| Derrubar só um enlace | `enlace off 10.G.R.1` nos dois lados, ou bloquear a porta no firewall |
| Mudar o custo de um enlace | Editar a linha nos dois arquivos e reiniciar os dois roteadores |
| Adicionar um vizinho | Uma linha nova nos dois arquivos e reiniciar os dois |
| Enviar pacote malformado | `injetor.py` a partir do `(ip, porta)` de um vizinho desligado (de outro par, é descartado antes do parse) |
| Ping para `10.G.R.77` | Respondido pelo roteador R, com origem `10.G.R.77` |
| Ping com TTL maior que o caminho | Resposta de eco normal |
| Mostrar um LSP sendo descartado como cópia | Log `LSP-DUPLICADO` em um roteador com dois caminhos até a origem |

### 7.4 Problemas comuns no dia

- **IP mudou (DHCP):** `ipconfig` (Windows) ou `ip a` (Linux) e editar a linha do vizinho.
- **Nada chega:** firewall bloqueando UDP de entrada; testar com `injetor.py` enviando um HELLO.
- **Porta ocupada:** outro roteador antigo ainda rodando; encerrar o processo.
- **Rotas "erradas" logo após subir:** aguardar 5 a 10 s; a sincronização depende do primeiro HELLO.

### 7.5 Treino para a regra sobre IA

Cada integrante explica em voz alta um módulo **que não escreveu**, e o grupo faz pelo menos uma rodada simulada de perguntas usando a seção 7.2, com o código aberto. Trecho que ninguém consegue explicar é reescrito de forma mais simples.

## 8. Relatório: experimentos e evidências

Todos os experimentos rodam na topologia de referência (seção 6.3), em uma máquina só, com captura do Wireshark na interface de loopback (`lo` no Linux, adaptador Npcap Loopback no Windows). Uma máquina só garante que os horários dos logs de todos os roteadores sejam comparáveis.

| Questão | Experimento | Evidência a anexar |
| --- | --- | --- |
| 1. Dijkstra | Saída de `lsdb` e `tabela` em R1; tabela de iterações feita à mão e conferida com `dijkstra_passos` | Prints dos comandos + tabela de iterações |
| 2. Inundação | Rede estável, captura ligada, derrubar um roteador; contar `LSP:` no Wireshark e `LSP-NOVO` / `LSP-DUPLICADO` com `analisar_logs.py` | `.pcapng` + contagem + comparação com a fórmula |
| 3. Convergência | Derrubar R3 (está no caminho R1→R5) e medir quando a rota de R1 para `10.G.5.0/24` passa de R2/5 para R4/6 | Linha do tempo com os horários dos logs |
| 4. Número de sequência | Reiniciar um roteador e mostrar que o novo LSP é aceito; discutir o caso de numeração a partir de 0 | Logs antes/depois |
| 5. Confiabilidade | Opção de teste que faz R1 perder o próximo LSP de R2; mostrar a LSDB desatualizada e a recuperação na renovação de 30 s | Logs + saída de `lsdb` |
| 6. TTL | Mesmo cenário da questão 5 com o enlace R2–R3 cortado: `ping` de R1 para R3 entra em laço R1↔R2 até o TTL zerar | Saída do `ping` (tempo excedido) + logs de `ENCAMINHADO` alternando |

**Questão 2, previsão teórica.** Numa rede conexa com N roteadores e E enlaces, uma inundação sem perdas gera:

```latex
\text{envios} = 2E - N + 1 \qquad \text{aceitos} = N - 1 \qquad \text{cópias descartadas} = 2(E - N + 1)
```

A origem envia a todos os seus vizinhos e cada outro roteador reenvia, uma única vez, a todos menos quem lhe mandou. Na topologia de referência (N = 5, E = 6) são 8 envios, 4 aceitos e 4 cópias. Na queda de um roteador com k vizinhos, **cada um dos k gera seu próprio LSP**, então há k inundações na rede restante, mais alguns envios perdidos para o roteador morto enquanto os outros ainda não detectaram a queda. Comparar com vetor de distância: lá cada roteador cujo vetor muda envia o vetor inteiro a todos os vizinhos, a mudança se propaga em ondas e, sem *split horizon*, pode haver contagem ao infinito.

**Questão 3, decomposição do tempo.** Detecção = do `derrubar` ao `VIZINHO-INATIVO` em R2 ou R4 (esperado 15 a 20 s, mais até 0,5 s do tick, porque o último HELLO pode ter chegado até 5 s antes da queda). Inundação = do `LSP-GERADO` em R2/R4 ao `LSP-NOVO` em R1 (milissegundos). Recálculo = campo `tempo` do `ROTAS-RECALCULADAS` (submilissegundo). A tabela de R1 pode mudar em mais de um passo, porque R2 e R4 detectam a queda em momentos diferentes.

**Questão 4.** Sem número de sequência não há como distinguir LSP novo de cópia ou de LSP atrasado, e a inundação não termina. Recomeçando de 0, os LSPs do roteador reiniciado teriam `seq` menor que o guardado pelos outros e seriam descartados até o antigo envelhecer (90 s); durante esse tempo os outros usam uma visão velha dos vizinhos dele.

**Questão 5.** LSP perdido deixa a LSDB de alguém desatualizada; a recuperação vem da renovação periódica a cada 30 s (e da sincronização quando um vizinho volta). O envelhecimento de 90 s limita por quanto tempo um LSP velho sobrevive.

**Questão 6.** Durante a convergência as LSDBs não são iguais. No experimento, R2 já sabe que o enlace R2–R3 caiu e manda o tráfego para R3 via R1, enquanto R1 ainda usa o LSP antigo de R2 e manda via R2. O TTL garante que o pacote morra (aqui, em R1 após 16 decrementos) em vez de circular para sempre.

A opção de teste das questões 5 e 6 deve ser determinística, por exemplo `--perder-proximo-lsp-de 10.G.2.1` (descarta só o próximo LSP daquela origem), para o experimento poder ser repetido. Na questão 6 o laço dura até a renovação seguinte de R2, no máximo 30 s, tempo de sobra para o `ping`.

## 9. Cronograma, divisão do trabalho e entrega

O plano cabe em cerca de 8 dias de trabalho e deve terminar antes da primeira aula de apresentação (prazo único para todos os grupos); ajustar os dias à data publicada no Moodle.

| Fase | Dias | Entregável | Pronto quando |
| --- | --- | --- | --- |
| 0. Base | 1 | Repositório, `config.py`, `pacotes.py`, `enderecos.py` | Testes P1 e X1 passam |
| 1. Estado de enlace | 2–3 | `vizinhos.py`, `lsdb.py`, inundação no `nucleo.py`, `RedeSimulada` | Testes V1–V5 e L1–L10 passam |
| 2. Roteamento | 3–4 | `dijkstra.py`, encaminhamento, ICMP, `cli.py` | Testes D1–D6, E1–E3 e I1–I7 passam |
| 3. Rede real | 5 | `udp.py`, threads, `log.py`, ferramentas | Topologia de 5 roteadores roda em localhost; teste O1 passa |
| 4. Experimentos | 6–7 | Capturas e logs das questões 1–6; ensaio na rede real; teste com outro grupo | `.pcapng` salvos; X2 feito com outro grupo |
| 5. Fechamento | 8 | Relatório PDF, README, `.zip`; guia de estudo em PDF; rodada simulada de perguntas | Checklist abaixo completo |

Divisão sugerida (cada um escreve os testes do módulo de **outro** integrante, o que obriga todos a entenderem o código inteiro):

| Integrante | Implementa | Escreve os testes de | Relatório |
| --- | --- | --- | --- |
| A | `config.py`, `pacotes.py`, `cli.py` | Dijkstra e tabela | Questões 1 e 4 |
| B | `vizinhos.py`, `lsdb.py`, inundação | Pacotes e terminal | Questões 2 e 5 |
| C | `dijkstra.py`, encaminhamento, ICMP | Vizinhança e LSDB | Questão 6 e figura da topologia |
| D | `udp.py`, `log.py`, `RedeSimulada`, ferramentas | Encaminhamento e ICMP | Questão 3 e capturas |

Em trio, D se divide entre A e B (A fica com `udp.py`, B com `log.py` e ferramentas).

### Checklist da entrega

- [ ] `.zip` com código-fonte, sem binários, `__pycache__` ou logs
- [ ] README: requisitos (Python 3.x), como executar, formato do arquivo de configuração com exemplo, comandos, opções de teste
- [ ] Relatório em PDF com a figura da topologia, as seis questões e as evidências
- [ ] Capturas `.pcapng` citadas no relatório
- [ ] `python -m unittest discover tests` passando em todas as máquinas do grupo
- [ ] Rede do grupo montada e testada no ambiente escolhido (VDI ou access point)
- [ ] Teste de interoperabilidade feito com pelo menos um outro grupo
- [ ] Guia de estudo em PDF (seção 10) pronto e todos os integrantes passaram pela rodada simulada de perguntas com ele
- [ ] Integrantes e data de apresentação informados no Moodle

## 10. Guia de estudo em PDF para a apresentação

O grupo deve produzir um **PDF de estudo** que explique o trabalho do problema ao código, e que **obrigatoriamente inclua um banco de perguntas que o professor pode fazer, cada uma com gabarito**. Como o enunciado zera o trabalho se o integrante questionado não souber explicar o código, esse PDF é a principal proteção do grupo: todos leem, todos treinam com ele.

### 10.1 Regras de produção

- **Quando:** na fase 5 (seção 9), depois do código congelado, para que nomes de arquivos, funções e trechos citados sejam os da versão entregue. Se o código mudar depois, o PDF é atualizado.
- **Quem:** cada integrante escreve os capítulos do módulo que **testou** (não o que implementou), e outro integrante revisa. Assim cada um precisa entender código alheio.
- **Tamanho:** 15 a 25 páginas. Linguagem simples, frases curtas, figuras sempre que houver fluxo ou topologia.
- **Rastreabilidade:** toda explicação de comportamento aponta o arquivo e a função (ex.: `nucleo.py: receber_lsp`). Todo gabarito também.
- **Formato:** pode ser escrito como doc e exportado em PDF, ou em Markdown convertido para PDF. Fica fora do `.zip` de entrega (é material interno), salvo se o grupo quiser anexá-lo.
- **Uso:** base da rodada simulada de perguntas (seção 7.5). Uma pessoa sorteia perguntas do banco e outra responde sem olhar o gabarito, com o código aberto.

### 10.2 Estrutura obrigatória do PDF

| Capítulo | O que precisa conter |
| --- | --- |
| 1. O problema | O que o trabalho pede: roteador de estado de enlace inspirado no OSPF, rodando sobre UDP; endereçamento virtual `10.G.R.1` e rede `10.G.R.0/24`; ambiente (VDI ou access point); restrições (UDP, ASCII, campos separados por `:`, sem bibliotecas de grafos); interoperabilidade com outro grupo; critérios de avaliação e pesos |
| 2. Conceitos necessários | Roteamento × encaminhamento; estado de enlace × vetor de distância; OSPF; HELLO e vizinhança; LSP, LSDB, inundação, número de sequência, envelhecimento; estado *soft* (expira se não renovado); Dijkstra e próximo salto; prefixo `/24`; TTL; ICMP tipos 0, 3, 8 e 11; traceroute por TTL crescente; UDP, socket e porta; rede sobreposta (*overlay*); threads e lock; convergência e laços transitórios |
| 3. Visão geral da solução | Diagrama da arquitetura (seção 2), papel de cada arquivo, as três threads, o núcleo sem I/O e por que essa separação foi escolhida |
| 4. Funcionamento passo a passo | Ciclo de vida do roteador (inicialização → HELLO → vizinho ativo → LSP → sincronização → LSDB → Dijkstra → tabela); um `ping` com TTL crescente seguido salto a salto, com as strings exatas dos pacotes; uma queda e a reconvergência, com os tempos de cada fase |
| 5. Formato dos pacotes | Os quatro formatos com exemplo, regras de validação e o que é considerado malformado |
| 6. Código explicado por módulo | Para cada arquivo: responsabilidade, funções principais, trechos-chave comentados e decisões tomadas (com o motivo) |
| 7. Dijkstra na topologia de referência | LSDB de R1, tabela de iterações (N', D(v), p(v)) e comparação com a saída do comando `tabela` |
| 8. Cenários "e se" | O que acontece em quedas, reinícios, perdas, custos diferentes, endereços duplicados, rede particionada, pacotes malformados |
| 9. Banco de perguntas com gabarito | No mínimo 60 perguntas, agrupadas por tema, cada uma com resposta de 1 a 3 frases e onde está no código; incluir as da seção 7.2 e as de 10.3 |
| 10. Roteiro e imprevistos | Roteiro da demonstração, pedidos ao vivo e problemas comuns (seções 7.1, 7.3 e 7.4) |

### 10.3 Banco inicial de perguntas com gabarito

Ponto de partida para o capítulo 9 do PDF. Complementa a seção 7.2; os gabaritos devem ganhar a referência ao código quando ele existir.

**Conceitos**

1. **Qual a diferença entre roteamento e encaminhamento?** Roteamento constrói a tabela (HELLO, LSP, Dijkstra). Encaminhamento usa a tabela para decidir, pacote a pacote, para onde mandar DADOS e ICMP.
2. **Qual a diferença entre estado de enlace e vetor de distância?** No estado de enlace cada roteador anuncia só seus enlaces para a rede toda e calcula as rotas com a topologia completa. No vetor de distância cada um envia sua tabela inteira só aos vizinhos e confia nas distâncias deles (Bellman-Ford), o que converge mais devagar e pode contar ao infinito.
3. **O que é a LSDB e por que todos precisam da mesma?** É o conjunto do LSP mais recente de cada roteador, ou seja, a topologia. Com LSDBs iguais, todos calculam rotas coerentes entre si e não há laços.
4. **Por que a rede é chamada de virtual?** Os endereços `10.G.R.x` existem só dentro das mensagens; o transporte real é UDP entre IPs reais. É uma rede sobreposta à rede local.
5. **O que significa `/24` aqui?** Os três primeiros octetos identificam a rede; qualquer endereço `10.G.R.x` pertence à rede do roteador R e é entregue a ele.
6. **O que é estado *soft*?** Estado que expira se não for renovado: vizinho sem HELLO por 20 s e LSP sem renovação por 90 s. É o que torna o protocolo robusto sobre UDP, que não confirma entrega.
7. **O que é convergência?** O momento em que, após uma mudança, todas as LSDBs voltam a ser iguais e as tabelas refletem a topologia nova.

**Vizinhança**

8. **Por que o HELLO vai também para vizinhos inativos?** Porque é o HELLO que torna o vizinho ativo; se cada lado esperasse o outro, nenhum enlace subiria.
9. **Se um único HELLO se perder, o vizinho cai?** Não. Só cai após 20 s sem HELLO, o que tolera até 3 perdas seguidas.
10. **Se o Wi-Fi de um roteador cair por 10 s e voltar, a rede percebe?** Não: o intervalo sem HELLO fica abaixo de 20 s, então nenhum vizinho fica inativo e nenhum LSP é gerado.
11. **Por que o endereço virtual do vizinho vem do HELLO e não do arquivo?** O arquivo só diz onde o vizinho pode estar (IP e porta); quem ele é só se sabe quando ele responde.

**LSPs e inundação**

12. **Por que renovar o LSP a cada 30 s se nada mudou?** Para recuperar LSPs perdidos e para que o LSP não envelheça nos outros roteadores.
13. **Por que o envelhecimento é 90 s e não 30 s?** 90 s são três renovações: o LSP só é removido se duas renovações seguidas se perderem, e não por um atraso pequeno.
14. **Por que não reenviar o LSP a quem o enviou?** Ele já tem essa versão; seria uma cópia descartada com certeza.
15. **Mesmo assim chegam cópias. Por quê?** Pelos ciclos da topologia: o mesmo LSP chega por mais de um caminho. Sem perdas, são 2(E − N + 1) cópias por inundação.
16. **O LSP próprio envelhece?** Não. O roteador é a fonte dele e o renova a cada 30 s.
17. **Um atacante (ou o professor) envia um LSP falso com `seq` enorme. O que acontece?** Se vier de um par `(ip, porta)` configurado, é aceito e inundado, porque o protocolo não tem autenticação; os LSPs verdadeiros daquela origem serão descartados até o falso envelhecer em 90 s. O OSPF real resolve com autenticação.
18. **E se dois roteadores usarem o mesmo endereço virtual?** Os dois geram LSPs da mesma origem com números de sequência diferentes; a LSDB fica alternando entre eles e as rotas ficam incoerentes. Por isso o endereço inclui G e R.

**Dijkstra e tabela**

19. **Explique o Dijkstra em três frases.** Começa do próprio roteador com custo 0. A cada passo fecha o nó aberto de menor custo e atualiza os vizinhos dele se o caminho por ele for mais barato. Termina quando não há mais nós alcançáveis abertos.
20. **Como `heapq` lida com um nó cujo custo diminuiu?** `heapq` não tem operação de diminuir chave: inserimos uma nova entrada e, quando a antiga sair da fila, ela é ignorada porque o nó já foi fechado.
21. **Por que o Dijkstra exige custos positivos?** Ele supõe que um nó fechado já tem o menor custo; com custo negativo, um caminho achado depois poderia ser mais barato. O enunciado garante inteiros positivos.
22. **Por que não há linha para a própria rede na tabela?** Pacotes para a própria `/24` são entregues localmente antes de qualquer consulta à tabela.
23. **Na topologia de referência, o que muda na tabela de R1 quando R3 cai?** R3 fica sem rota, R4 passa de R2/4 para R4/5 (enlace direto) e R5 de R2/5 para R4/6, cerca de 15 a 20 s depois da queda.

**Encaminhamento, TTL e ICMP**

24. **`ping` com TTL 1 para um vizinho direto: o que volta?** Resposta de eco, não tempo excedido: o vizinho verifica primeiro se o destino é a própria rede e só depois mexeria no TTL.
25. **Por que as mensagens de erro saem com TTL 16 e não com o TTL restante?** São pacotes novos, criados pelo roteador que detectou o erro, e todo pacote novo começa com 16.
26. **Quando aparece um ICMP 3 vindo de outro roteador, e não da origem?** Quando a origem tem rota mas um roteador do caminho não tem, por exemplo durante a convergência ou com LSDBs diferentes.
27. **Quando o `ping` dá timeout?** Quando nenhuma resposta chega em 2 s: o destino caiu e a rota ainda existe (antes da detecção), ou um pacote se perdeu.
28. **Como o RTT é medido e como a resposta certa é encontrada?** O horário de envio fica guardado pelo id do pedido; a resposta (tipo 0, 3 ou 11) traz o mesmo id, e o RTT é a diferença de horários.
29. **E uma `msg` com acento ou com `:`?** O terminal recusa antes de enviar; se chegar de fora, é descartada como malformada.

**Implementação**

30. **Que problema o lock evita?** Por exemplo, a thread de recepção inserindo um LSP enquanto o temporizador percorre a LSDB para envelhecer entradas: sem o lock, o dicionário muda durante a iteração e o programa quebra ou perde dados.
31. **Por que `time.monotonic()` nos temporizadores?** Porque não volta para trás se o relógio do sistema for ajustado; `time.time()` fica só para o primeiro `seq` e para os logs.
32. **Como vocês testaram o envelhecimento de 90 s sem esperar 90 s?** O núcleo recebe o horário como parâmetro; nos testes usamos um relógio falso e avançamos 90 s instantaneamente.
33. **Por que o roteador não cai com um pacote malformado?** O parse levanta uma exceção específica que é capturada no laço de recepção; o pacote é registrado e descartado e o laço continua.

**Relatório**

34. **As seis questões do relatório.** Cada integrante deve saber responder todas de memória, com os números medidos pelo grupo; os gabaritos-base estão na seção 8.
