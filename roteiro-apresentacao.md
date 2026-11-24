# Roteiro de apresentação — grupo 99 — VDI

Trio. Um roteador por máquina virtual. Sugestão, pode trocar: Juliano no R1, Gabriel no R2, Leonardo no R3.

Enlaces: R1–R2 custa 1, R2–R3 custa 2, R1–R3 custa 5.

No estado normal, R1 chega em R3 por R2 (custo 3), não pelo enlace direto (custo 5).

## Ensaio nesta máquina, agora

No Windows, na pasta do projeto, com os cinco roteadores do relatório já encerrados:

```text
python ferramentas/subir_topologia.py encerrar
python ferramentas/subir_topologia.py --diretorio config/apresentacao
```

Abrem três janelas, portas 6001, 6002 e 6003, todas em 127.0.0.1. Espere uns 15 segundos. Siga a seção "Os 10 minutos" nas janelas. Para simular o professor derrubando o R2:

```text
python ferramentas/subir_topologia.py derrubar 2
```

Espere uns 25 segundos e repita o ping. Para o R2 voltar:

```text
python ferramentas/subir_topologia.py religar 2
```

No fim:

```text
python ferramentas/subir_topologia.py encerrar
```

No macOS e no Linux, abra três terminais na pasta do projeto e execute um
comando por terminal:

```text
python -m roteador config/apresentacao/r1.txt
python -m roteador config/apresentacao/r2.txt
python -m roteador config/apresentacao/r3.txt
```

Para simular a queda de R2, use `sair` no terminal dele e espere 25 segundos.
Para religá-lo, execute o mesmo comando de novo. No fim, use `sair` em cada
terminal.

## Na VDI, antes de começar

Cada um, na própria VM:

1. Copie a pasta do projeto para a VM.
2. `ipconfig`. Anote o IPv4. Não use 127.0.0.1.
3. Edite só o próprio arquivo em `config/vdi/`:
   - R1 edita `r1.txt`
   - R2 edita `r2.txt`
   - R3 edita `r3.txt`
4. Troque `IP_DO_R1`, `IP_DO_R2` e `IP_DO_R3` pelo IPv4 de cada um. Os dois lados do enlace usam o mesmo custo. A porta é 6000 nas três VMs.
5. Se o HELLO não chegar, libere UDP 6000 de entrada no firewall da VM.
6. Cada um sobe só o próprio roteador, na pasta do projeto:

```text
python -m roteador config/vdi/r1.txt
python -m roteador config/vdi/r2.txt
python -m roteador config/vdi/r3.txt
```

A janela tem de dizer `roteador 10.99.R.1 escutando UDP 6000`. A rede precisa estar no ar quando a dupla for chamada. Não fechem as janelas.

## Os 10 minutos

Esperem uns 15 segundos depois da subida. Em cada janela, `vizinhos` mostra os dois outros como `ativo`.

### 1. Conferir a topologia

Cada um digita, nesta ordem:

```text
vizinhos
lsdb
tabela
```

O que tem de aparecer.

R1, `tabela`:

```text
10.99.2.0/24    10.99.2.1    1
10.99.3.0/24    10.99.2.1    3
```

R2, `tabela`:

```text
10.99.1.0/24    10.99.1.1    1
10.99.3.0/24    10.99.3.1    2
```

R3, `tabela`:

```text
10.99.1.0/24    10.99.2.1    3
10.99.2.0/24    10.99.2.1    2
```

R3 não usa o enlace direto com R1. Esse enlace custa 5. O caminho R3–R2–R1 custa 3.

No `lsdb` dos três, as mesmas três entradas: R1 com `10.99.2.1=1;10.99.3.1=5`, R2 com `10.99.1.1=1;10.99.3.1=2`, R3 com `10.99.1.1=5;10.99.2.1=2`.

### 2. Ping com TTL crescente e uma mensagem

No R1:

```text
ping 10.99.3.1 1
ping 10.99.3.1 2
msg 10.99.3.1 oi
```

Respostas no R1:

```text
tempo excedido de 10.99.2.1
eco de 10.99.3.1
msg enviada para 10.99.3.1
```

No R3 aparece:

```text
mensagem de 10.99.1.1 para 10.99.3.1: oi
```

TTL 1 para um vizinho direto seria eco, porque o destino é conferido antes de mexer no TTL. Aqui o destino é o R3, e o primeiro salto é o R2. O R2 zera o TTL e devolve tempo excedido. Com TTL 2 o R3 recebe o pedido e responde eco.

### 3. Rede que não existe

No R1:

```text
ping 10.99.9.1
```

Resposta, sem enviar pacote:

```text
destino inalcancavel: 10.99.9.1
```

### 4. Queda

O professor derruba um roteador ou um enlace. A detecção leva cerca de 20 segundos sem HELLO. Não digitem nada nesse intervalo. Quando o log mostrar `VIZINHO-INATIVO`, mostrem `tabela` de novo e repitam o ping.

Se cair o R2, que é o caso mais claro:

No R1, a `tabela` fica só com:

```text
10.99.3.0/24    10.99.3.1    5
```

A rota de R2 some. O caminho passa a ser o enlace direto.

```text
ping 10.99.3.1 1
```

Agora a resposta é `eco de 10.99.3.1`, porque R3 virou vizinho de um salto só.

Se cair o R3, a rota para `10.99.3.0/24` some nos outros dois. `ping 10.99.3.1` passa a responder `destino inalcancavel: 10.99.3.1`. Não há caminho novo para mostrar. Digam isso e sigam.

Se cair o R1, R3 pode mostrar que `ping 10.99.1.1` fica inalcançável e que
R2 continua acessível com `ping 10.99.2.1 1`.

Se cair só o enlace R2–R3, R3 pode mostrar a rota alternativa para R1:

```text
ping 10.99.1.1 1
```

Antes da queda do enlace, R2 devolve tempo excedido. Depois, R1 responde
ao eco pelo enlace direto de custo 5.

Quando o professor mandar religar, a pessoa sobe de novo o mesmo comando (`python -m roteador config/vdi/rN.txt`). Esperem uns 15 segundos. A `tabela` volta ao normal. O LSP novo tem sequência maior e é aceito.

## Teste com o outro grupo

Combinem antes, por mensagem:

- o número G deles
- qual roteador deles entra no enlace, no formato `10.G.R.1`
- o IPv4 da VM desse roteador
- a porta, em geral 6000
- um custo igual dos dois lados, por exemplo 2
- o nosso lado é o R1: passem a eles o IPv4 da VM do R1

No `config/vdi/r1.txt`, descomentem a última linha e preencham:

```text
vizinho IP_DO_OUTRO_GRUPO 6000 2
```

Eles acrescentam, no roteador escolhido:

```text
vizinho IP_DA_NOSSA_VM_R1 6000 2
```

Os dois reiniciam só esse roteador. O arquivo só é lido na subida. Esperem uns 15 segundos.

No R1:

```text
vizinhos
lsdb
tabela
```

`vizinhos` mostra o roteador deles como `ativo`, além de R2 e R3. O `lsdb` ganha a origem `10.G.R.1`. A `tabela` ganha a rede `10.G.R.0/24`, com próximo salto igual ao endereço virtual deles e custo 2.

Do R3, para atravessar a nossa rede e a deles. Troquem `10.G.R.1` pelo endereço combinado.

```text
ping 10.G.R.1 1
ping 10.G.R.1 2
ping 10.G.R.1 3
msg 10.G.R.1 oi do grupo 99
```

O caminho é R3, R2, R1, roteador deles. TTL 1 é tempo excedido do R2. TTL 2 é tempo excedido do R1. TTL 3 é eco do endereço deles. A `msg` aparece no terminal deles.

Se o primeiro ping já voltar eco, o pacote achou um caminho mais curto. Subam o TTL de um em um até o eco e leiam, em cada tempo excedido, quem respondeu. Esse nome é o salto.

Para ensaiar o corte do enlace entre os grupos, no R1, com o virtual deles no lugar de `10.G.R.1`:

```text
enlace off 10.G.R.1
```

Esperem uns 25 segundos. A rede `10.G.R.0/24` some da `tabela` do R1, do R2 e do R3. `ping 10.G.R.1` responde `destino inalcancavel`. Para religar:

```text
enlace on 10.G.R.1
```

Mais uns 15 segundos e a rota volta. No dia, quem corta é o professor. Vocês só mostram a `tabela` e o ping.
