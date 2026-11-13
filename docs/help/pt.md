<!--
Guia do usuário do Accessible IPTV Client, em português do Brasil. A
referência em inglês está em docs/help/en.md. Nota para tradutores: manter os
identificadores {#topic ID} como estão; traduzir apenas o texto do título.
Uma seção ainda não traduzida pode simplesmente ser omitida; o F1 abrirá
então a seção em inglês.
-->

# Guia do usuário do Accessible IPTV Client {#user-guide}

O Accessible IPTV Client reproduz televisão ao vivo, rádio e vídeo sob demanda de provedores IPTV. Foi construído para o teclado e para leitores de tela como NVDA, JAWS, Narrator e Orca, e lida com listas de reprodução e guias de programação muito grandes.

Este guia explica cada parte do programa. Pressione F1 em qualquer lugar do programa para abri-lo na seção sobre o que você está usando naquele momento.

## Usando este guia {#using-help}

A janela do guia tem quatro partes, na ordem de tabulação:

- Tópicos: a lista de seções. Mover-se por ela com as setas move o texto do guia para essa seção. Pressione Enter para entrar direto no texto.
- Texto do guia: todo o guia como um único documento de somente leitura. Leia-o com as setas ou com o comando de leitura contínua do seu leitor de tela; selecionar e copiar texto funciona como em qualquer documento.
- Localizar: digite uma palavra e pressione Enter para saltar ao próximo lugar em que ela aparece.
- Fechar.

Teclas na janela do guia:

- Ctrl+F: ir para o campo Localizar.
- F3: localizar a próxima ocorrência. Shift+F3: localizar a anterior.
- F1: voltar a esta seção.
- Escape: fechar o guia e voltar a onde você estava.

O F1 é sensível ao contexto. Pressionado em um item de menu, em uma janela de diálogo, no reprodutor integrado ou em um controle da janela principal, ele abre o guia na seção sobre aquele item. Onde ainda não há uma seção escrita, o guia abre no começo. Ajuda > Guia do usuário sempre abre no começo.

O guia faz parte do programa, então funciona sem conexão com a Internet. É mostrado no idioma da interface do programa quando existe tradução, e em inglês caso contrário.

## Primeiros passos {#getting-started}

1. Abra Arquivo > Gerenciador de listas de reprodução (Ctrl+M) e adicione seu provedor: um arquivo ou endereço de lista M3U, uma conta Xtream Codes, ou uma conta Stalker Portal. Escolha OK. Os canais carregam em segundo plano.
2. Se o seu provedor lhe dá um endereço de guia de programação (EPG), adicione-o em Arquivo > Gerenciador de EPG (Ctrl+E). Contas Xtream Codes podem adicioná-lo por você.
3. Importe o guia com Arquivo > Importar EPG para o banco de dados (Ctrl+I). Isso roda em segundo plano e avisa quando termina.
4. Escolha uma categoria, escolha um canal e pressione Enter para reproduzi-lo.

Suas listas de reprodução, fontes de guia e configurações são mantidas entre sessões, então isso só precisa ser feito uma vez.

## A janela principal {#main-window}

A janela principal é onde você navega e reproduz canais. Tab passa pelos controles nesta ordem, e Shift+Tab volta:

1. Vista da lista de reprodução: qual lista navegar.
2. Categorias: os grupos de canais.
3. Pesquisar: filtra a lista de canais.
4. Canais: os canais da categoria escolhida, ou os resultados da pesquisa.
5. Descrição do episódio: o que está no ar agora no canal destacado.
6. URL da transmissão: o endereço do canal destacado, mostrado apenas quando Opções > Mostrar o URL da transmissão está ligado.

Depois do último controle, Tab volta ao primeiro.

No Linux, os menus que este guia descreve ficam sob o botão Menu no topo da janela.

### Vista da lista de reprodução {#playlist-view}

Quando você tem mais de uma lista de reprodução, a lista Vista da lista de reprodução escolhe o que as categorias e os canais mostram: todas as listas, ou uma só. Sua escolha é lembrada.

### Categorias {#categories}

A lista de categorias contém os grupos de canais das suas listas. Suas primeiras linhas são Todos os canais e, depois de adicionar alguns, Favoritos. Cada linha diz quantos canais contém.

- As setas para cima e para baixo percorrem as categorias sem mudar a lista de canais, para que você possa ouvi-las primeiro.
- Enter abre a categoria destacada e passa para a lista de canais.
- Tab abre a categoria destacada e passa para o campo Pesquisar.
- As setas para a esquerda e para a direita recolhem e expandem uma categoria com subgrupos.

### Pesquisa {#search}

Digite no campo Pesquisar para filtrar a lista de canais, e pressione Enter ou Tab para aplicar o filtro e seguir. Pesquisar em Todos os canais também consulta o guia de programação, então uma pesquisa pelo título de um programa pode listar os canais que o exibem. Esvazie o campo e pressione Enter para ver a categoria inteira de novo.

### A lista de canais {#channel-list}

A lista de canais mostra os canais da categoria ou pesquisa escolhida.

- Enter reproduz o canal destacado.
- A tecla de menu de aplicativo, Shift+F10 ou um clique com o botão direito abre o menu do canal: Reproduzir, Adicionar aos favoritos ou Remover dos favoritos, Gravar ou Parar gravação, Agendar gravação, Exibir EPG…, e Replay para canais que têm arquivo.
- Ctrl+D adiciona o canal aos favoritos ou o remove. Na categoria Favoritos, Delete o remove.
- Ctrl+Shift+R inicia a gravação do canal; pressionado de novo, ela para.
- Ctrl+G pede um número de canal e reproduz o canal correspondente. Ctrl+0 retorna ao canal anterior e Ctrl+H abre Assistidos recentemente.
- Ctrl+Shift+I anuncia o canal atual, os horários dos programas, o próximo programa e o status da gravação sem mover o foco.

Os canais favoritos são marcados com "(Favorito)", e cada linha também nomeia o programa no ar quando o guia o tem. Quando uma pesquisa também encontrou programas, suas linhas nomeiam o programa e o canal em que ele passa.

### Descrição do episódio e URL da transmissão {#episode-description}

Tab a partir da lista de canais chega à Descrição do episódio: o programa no ar no canal destacado, com seus horários e descrição, e o que vem a seguir. Shift+Tab volta direto para a lista de canais. O texto segue o canal destacado.

Quando Opções > Mostrar o URL da transmissão está ligado, o campo URL da transmissão vem um Tab depois. Ele mostra o endereço do canal, o que ajuda ao relatar um problema. A maioria o deixa desligado.

## Favoritos {#favorites}

Os favoritos mantêm em um só lugar os canais que você mais assiste. Pressione Ctrl+D em um canal, use o menu dele, ou Exibir > Adicionar aos favoritos. Os favoritos aparecem na categoria Favoritos perto do começo da lista de categorias, e Exibir > Ir para os favoritos leva você até lá.

Para remover um favorito, pressione Ctrl+D nele de novo, ou pressione Delete na categoria Favoritos.

Os favoritos são guardados por provedor e canal, não por endereço de transmissão, então sobrevivem a uma atualização da lista. Nada da sua conta é guardado com eles.

Ver > Assistidos recentemente lista os canais que você reproduziu. Ver > Canal Anterior (Ctrl+0) volta para o canal que você assistiu antes deste.

## Vídeo sob demanda {#video-on-demand}

Exibir > Vídeo sob demanda (filmes && séries) troca a lista de categorias dos canais ao vivo para os filmes e as séries do seu provedor. As categorias se chamam Movies ou Series seguidos da categoria do provedor. Escolher uma série lista seus episódios em ordem de temporada e episódio. Pressione Enter para reproduzir um filme ou um episódio.

Exibir > TV ao vivo && Replay volta aos canais ao vivo. O campo de pesquisa é esvaziado ao trocar.

O vídeo sob demanda funciona melhor com contas Xtream Codes, que descrevem bem o catálogo delas. Para listas M3U simples, o programa reconhece filmes e séries pelos nomes dos grupos e pela numeração dos episódios.

Reprodutor > Reproduzir automaticamente o próximo episódio vem desativado. Quando ativado, um episódio encerrado normalmente inicia uma contagem de dez segundos para o próximo identificado. Reproduzir agora começa imediatamente; Cancelar ou Escape impede a continuação. Uma parada manual ou falha antecipada não a inicia. Mudanças na reprodução ou na lista invalidam uma continuação desatualizada; sem um próximo episódio identificado sem ambiguidade, a reprodução termina.

## Gerenciador de listas de reprodução {#playlist-manager}

Arquivo > Gerenciador de listas de reprodução (Ctrl+M) lista suas fontes de listas de reprodução. Ele abre com o foco na lista.

- Adicionar arquivo: uma lista M3U ou M3U8 no seu computador.
- Adicionar URL: o endereço da Internet de uma lista M3U.
- Adicionar Xtream Codes: uma conta Xtream Codes.
- Adicionar Stalker Portal: uma conta de portal Stalker (MAG).

Sobre uma fonte da lista, a tecla de menu de aplicativo ou Shift+F10 abre o menu dela: Copiar URL, Renomear (F2) e Eliminar (Delete). Um nome que você dá a uma fonte é só um rótulo; ele não muda a fonte.

Atualizar (F5) no mesmo menu baixa essa lista de novo e recarrega os canais, avisando quando termina. Uma lista nova precisa ser salva com OK antes. As listas também são atualizadas sempre que o programa inicia e a cada três horas. Só a lista destacada é atualizada; as outras mantêm seus canais. Para atualizar todas as listas, pressione Ctrl+A na lista antes.

Escolha OK para manter suas mudanças, ou Cancelar para descartá-las. Os canais recarregam depois de OK.

### Contas Xtream Codes {#xtream-codes}

Uma conta Xtream Codes precisa do endereço do servidor, do seu nome de usuário e da sua senha, que seu provedor fornece. O nome é o seu próprio rótulo para a conta. Deixe "Adicionar automaticamente a URL do XMLTV" marcada para adicionar o guia do provedor ao Gerenciador de EPG ao mesmo tempo.

Contas Xtream Codes também lhe dão vídeo sob demanda, replay quando o provedor oferece, e o estado da conta em Arquivo > Informações da conta.

### Contas Stalker Portal {#stalker-portal}

Uma conta Stalker Portal precisa do endereço do portal e do endereço MAC que seu provedor registrou para você. Alguns portais também pedem usuário e senha. "MAC aleatório" inventa um novo endereço MAC, útil apenas quando o provedor pede para você escolher um. "Tentar adicionar o XMLTV do provedor" adiciona o guia do portal quando ele tem um.

## Guia de programação (EPG) {#epg}

O guia de programação, ou EPG, diz o que passa em cada canal agora e depois. Ele vem de arquivos XMLTV publicados pelo seu provedor ou por outra fonte. O programa os importa para um banco de dados local, e o usa para a descrição do episódio, No ar agora, Exibir EPG…, listas de replay e pesquisas.

Exibir > Associar guia de programação permite escolher o canal do guia correspondente ao canal ao vivo selecionado. Pesquise pelo nome ou identificador, selecione uma entrada e pressione OK. Usar associação automática remove a escolha manual. A escolha é salva separadamente por lista ou provedor e vale para títulos de programas, guia, pesquisas e gravações agendadas. Se o identificador desaparecer após uma importação, os dados do programa ficarão indisponíveis até que a escolha seja corrigida ou a associação automática seja restaurada.

### Gerenciador de EPG {#epg-manager}

Arquivo > Gerenciador de EPG (Ctrl+E) lista suas fontes de guia.

- Adicionar arquivo: um arquivo XMLTV no seu computador (.xml ou .xml.gz).
- Adicionar URL: o endereço da Internet de um guia XMLTV.

Usar também o EPG indicado por cada lista de reprodução: muitas listas indicam o próprio EPG na primeira linha. Enquanto esta caixa estiver marcada (padrão), esses EPGs são importados junto com as fontes acima, e um EPG que você já adicionou não é importado duas vezes.

A tecla de menu de aplicativo ou Shift+F10 sobre uma fonte abre o menu dela: Copiar URL, Renomear (F2) e Eliminar (Delete). Escolha OK para manter suas mudanças.

### Importar o guia {#import-epg}

Arquivo > Importar EPG para o banco de dados (Ctrl+I) baixa cada fonte de guia e a carrega no banco de dados do guia. Ele roda em segundo plano, então você pode continuar assistindo e navegando, e uma mensagem avisa quando termina. Guias grandes podem levar vários minutos.

O guia também é atualizado automaticamente de tempos em tempos, em silêncio. Os canais são pareados com o guia pelo identificador e pelos nomes, incluindo as variações habituais de país e qualidade nos nomes dos canais.

Se um guia importado não aparece para um canal, confira se uma das suas fontes o cobre, e importe de novo. A importação escreve um registro detalhado; veja Solução de problemas.

### No ar agora {#whats-on-now}

Arquivo > No ar agora (Ctrl+W) lista todo programa no ar agora em todos os canais, como "programa - canal".

- Digitar letras salta para o primeiro programa que começa com elas.
- Tab passa para o campo Filtro; digitar lá estreita a lista aos programas ou canais correspondentes.
- Enter ou o botão Reproduzir reproduz o canal.
- Agendar gravação, ou o menu do programa, agenda a gravação dele.
- Escape fecha a janela.

### Guia do canal (Exibir EPG) {#channel-epg}

Exibir EPG…, no menu de um canal, lista os programas daquele canal do que está no ar até onde o guia alcança. O programa no ar vem primeiro.

- Tab alterna entre a lista e a descrição do programa destacado.
- A tecla de menu de aplicativo ou Shift+F10 sobre um programa oferece Agendar gravação.
- Escape fecha a janela.

## Replay {#catch-up}

Canais que guardam um arquivo permitem assistir programas que já foram transmitidos. Esses canais têm Replay no menu deles na lista de canais. Ele abre a janela de replay do canal, listando os programas passados com data e hora.

- As setas para cima e para baixo percorrem os programas.
- Enter reproduz o programa destacado.
- A tecla de menu de aplicativo ou Shift+F10 abre o menu dele: Abrir, para reproduzi-lo, e Transferir, para salvá-lo como arquivo.
- Tab passa para a descrição do programa e volta.
- Escape fecha a janela.

Ao fechar o reprodutor integrado depois de assistir um programa de replay, você volta à lista de replay no mesmo programa.

Quanto para trás você pode ir depende do seu provedor, normalmente alguns dias.

### Transferências de replay {#catch-up-downloads}

Transferir salva um programa de replay na sua pasta de download (veja Gravações), nomeado pelo canal e pela transmissão do programa. Cada transferência tem a própria janela com progresso, tempo decorrido, tempo restante e tamanho até agora, tudo em um campo de somente leitura.

- Escape, ou fechar a janela, a esconde; a transferência continua.
- Exibir > Mostrar transferências (Ctrl+Shift+D) traz de volta as janelas de transferência.
- Cancelar para a transferência após pedir confirmação. Uma transferência cancelada não pode ser retomada.

Se uma transferência falha, a janela diz por quê e tenta de novo sozinha algumas vezes quando o problema pode ser temporário. Muitos provedores permitem só um fluxo por vez; pare outra reprodução da mesma conta se uma transferência é recusada.

## Reprodutor integrado {#built-in-player}

O reprodutor integrado reproduz canais dentro do programa. Ele abre quando você reproduz um canal, a menos que Opções > Mostrar o reprodutor ao pressionar Enter esteja desligado; nesse caso a reprodução começa sem mostrar a janela.

Os controles dele, na ordem de tabulação: Reproduzir/Pausar, Parar, Gravar, Transmitir, Tela cheia, o controle deslizante de Volume e Escolher faixa de áudio.

Teclas no reprodutor:

- Espaço: pressiona o botão com foco, então em Reproduzir/Pausar pausa e retoma.
- Ctrl+P: reproduzir ou pausar.
- Ctrl+S: parar.
- Ctrl+R: gravar o que você está assistindo, e parar essa gravação.
- Setas para cima e para baixo: volume em passos de 2%. Ctrl+Acima e Ctrl+Abaixo: passos de 5%.
- A: próxima faixa de áudio.
- S: próxima faixa de legenda, incluindo Off. Reprodução > Legendas permite escolher uma faixa ou carregar um arquivo de legenda externo.
- Shift+S: ativar ou desativar a leitura de legendas.
- C: ler a legenda atual, ou a última mostrada.
- Page Up e Page Down: voltar pelas legendas já mostradas e avançar de novo até a mais recente.
- I: anuncia o canal atual, horários dos programas, próximo programa e status da gravação.
- D: escolher o dispositivo de saída de áudio.
- Ctrl+C: transmitir para um dispositivo.
- F11: tela cheia ligada ou desligada. Escape sai dela.
- Ctrl+W: ocultar a janela do reprodutor; a reprodução continua.
- Ctrl+Q: fechar o reprodutor e parar a reprodução.

Os mesmos comandos estão no menu Reprodução do reprodutor. O reprodutor se reconecta sozinho quando um fluxo ao vivo cai, e mantém a faixa de áudio que você escolheu.

Silenciar / Ativar som silencia o player integrado sem pausar a reprodução nem a gravação. Os atalhos padrão são Ctrl+Shift+M na janela principal e M no player; ambos podem ser alterados nas configurações de atalhos. O som continua desativado ao mudar de canal ou reconectar. Reprodutor > Lembrar o volume de cada canal começa desativado e, quando ativado, memoriza o volume escolhido separadamente por lista ou provedor. Canais sem valor salvo usam o volume geral do player. Nenhuma dessas funções altera o volume do leitor de tela.

No menu Reprodução do reprodutor integrado, Adicionar marcador com nome salva a posição atual de conteúdo sob demanda ou de uma gravação local. É necessário poder avançar ou retroceder e conhecer a duração. Marcadores com nome lista os marcadores do conteúdo atual: Enter ou Ir para o marcador abre a posição; Renomear e Excluir gerenciam a entrada selecionada. Os nomes devem ser únicos no mesmo conteúdo. Podem ser salvos até 1000 marcadores no total, separados da posição automática de retomada.

### Faixas de áudio {#audio-tracks}

Canais podem carregar várias faixas de áudio, como outros idiomas ou audiodescrição. Pressione A para ir à próxima faixa, use Reprodução > Faixa de áudio, ou Tab até Escolher faixa de áudio, que sempre nomeia a faixa em reprodução.

Uma faixa que você escolhe é lembrada para aquele canal e volta na próxima vez. Para escolhê-las automaticamente, veja Faixa de áudio preferida.

### Leitura de legendas {#subtitle-speech}

O texto da legenda aparece no vídeo quando o stream o fornece. Reprodução > Carregar arquivo de legenda aceita um arquivo de legenda externo. Ative Reprodução > Ler legendas em voz alta (Shift+S) e a voz selecionada lerá cada legenda de um arquivo SRT, ASS, SSA ou WebVTT carregado assim que ela aparecer, também com a janela do player oculta. A legenda atual também é mostrada como texto no final dos controles do player. O player integrado ainda não pode ler em voz alta as legendas incluídas no próprio stream.

Reprodução > Ler a legenda atual (C) lê a legenda que está na tela, ou a última mostrada quando não há nenhuma na tela. Reprodução > Legenda anterior (Page Up) e Próxima legenda (Page Down) percorrem as legendas já mostradas, para você ouvir de novo uma linha que perdeu. Elas nunca leem à frente da reprodução e funcionam com Ler legendas em voz alta ativado ou desativado. No Windows, Opções > Leitura de legendas > Velocidade da voz da aplicação… permite escolher um valor de -10 a 10; 0 é normal. Isso não altera a velocidade de reprodução nem as configurações do leitor de tela.
### Dispositivo de saída de áudio {#audio-output-device}

Reprodução > Dispositivo de saída de áudio… (D) escolhe os alto-falantes ou fones que o reprodutor usa, por exemplo para manter o som da TV longe do seu leitor de tela. Predefinido do sistema segue o dispositivo predefinido do Windows. A escolha é lembrada.

### Controlar o reprodutor pela janela principal {#player-from-main-window}

O menu Reprodutor da janela principal atua no reprodutor integrado sem trocar para ele:

- Mostrar reprodutor integrado: Ctrl+Shift+J.
- Reproduzir/Pausar: Ctrl+Shift+P.
- Parar: Ctrl+Shift+S.
- Transmitir / Conectar…: Ctrl+Shift+C.
- Ctrl+Acima e Ctrl+Abaixo mudam o volume.

## Reprodutor de mídia {#media-player}

Opções > Reprodutor de mídia a usar escolhe o que reproduz seus canais: o Reprodutor integrado, ou um reprodutor externo como VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi ou SMPlayer. Reprodutor personalizado… permite escolher qualquer outro programa pelo arquivo dele.

Gravação, transferências de replay e transmissão funcionam igual com o reprodutor que escolher. Os recursos de faixa de áudio e as teclas do reprodutor descritas neste guia pertencem ao reprodutor integrado.

## Faixa de áudio preferida {#preferred-audio-track}

Opções > Faixa de áudio preferida faz o reprodutor integrado escolher uma faixa de áudio por si mesmo.

- "Preferir uma faixa de audiodescrição quando o canal tiver uma" escolhe audiodescrição onde quer que seja oferecida. Ela reconhece os nomes que os provedores realmente usam em vários idiomas, como audio description, AD, Audiodeskription e Hörfilm, e a marcação que emissoras põem em tais faixas.
- O campo de texto aceita nomes de faixas ou idiomas, os mais desejados primeiro, separados por vírgulas, por exemplo: audio description, Portuguese. Deixe-o vazio para manter a faixa com que um canal começa.

Uma faixa que você escolhe à mão no reprodutor é lembrada para aquele canal e tem prioridade sobre essas regras na próxima vez que você o assistir. A última faixa escolhida em qualquer lugar é usada nos canais para os quais você nunca escolheu uma.

As gravações seguem a mesma escolha. Uma gravação de só áudio mantém a única faixa que você ouviria, e uma gravação de vídeo mantém todas as faixas marcando essa como padrão.

## Gravações {#recordings}

O programa pode gravar qualquer canal para um arquivo enquanto você assiste outra coisa, ou sem nada reproduzindo.

- Gravações > Iniciar gravação (Ctrl+Shift+R) grava o canal destacado. Pressionado de novo, ela para.
- Gravar no menu de um canal faz o mesmo, e Gravar no reprodutor integrado (Ctrl+R) grava o que você está assistindo.
- Gravações > Parar gravação para a gravação do canal destacado, e Parar todas as gravações para todas.
- Gravações > Abrir pasta de gravações abre a pasta onde os arquivos são guardados.
- Gravações > Definir pasta de descarga… escolhe essa pasta. As transferências de replay também vão para lá.
- Cada gravação escreve um arquivo de registro na pasta logs, dentro da pasta de gravações. Se uma gravação terminar com um aviso ou erro, a mensagem inclui um resumo das linhas de aviso, erro e erro fatal encontradas no registro. Abra o registro para ver os detalhes. O registro termina com um resumo: quanto a gravação deveria durar, quanto durou de fato e todos os avisos e erros agrupados por tipo, com os momentos em que ocorreram.

Gravar o que você está assistindo no reprodutor integrado usa a mesma conexão com o provedor, então funciona mesmo com contas que permitem só um fluxo por vez.

Parar uma gravação pode levar um momento enquanto o arquivo é finalizado. Ao sair do aplicativo, as gravações ainda em andamento também são paradas; antes, o programa lhes dá um curto intervalo para finalizar os arquivos.

Gravações > Monitoramento do espaço de gravação verifica o espaço livre a cada cinco segundos durante a gravação. O aviso está ativado por padrão abaixo de 1024 MiB. A parada automática começa desativada; ative-a e escolha um limite, inicialmente de 256 MiB, para solicitar o fechamento correto dos arquivos antes que a unidade fique cheia. O limite de aviso não pode ser menor que o de parada. Gravações na mesma unidade compartilham um aviso; com a parada ativada, todas as afetadas são encerradas. A verificação não reserva espaço nem garante o fechamento dos arquivos em uma unidade cheia ou desconectada.

Gravações > Biblioteca de gravações lista arquivos concluídos de até 20 pastas, incluindo a pasta de gravação atual. Adicionar pasta inclui uma pasta existente sem mudar o destino das novas gravações. Remover pasta da biblioteca mantém os arquivos intactos. A pasta de gravação atual não pode ser removida.

Pesquise por título, canal ou data. Reproduzir / Retomar abre o arquivo e oferece a posição salva, quando disponível. Duração e estado aparecem quando conhecidos; arquivos antigos podem indicar Desconhecido. Gravações em andamento e arquivos abertos no reprodutor integrado são excluídos. Renomear título altera apenas o título exibido, preservando o nome do arquivo, a posição e os marcadores. Atualizar recarrega a lista.

Mover para a lixeira de gravações transfere o arquivo para a lixeira do aplicativo dentro da sua pasta de gravação, sem liberar espaço. Mostrar gravações excluídas exibe esses arquivos. Restaurar gravação devolve o arquivo à pasta original sem substituir arquivos existentes. Nessa visualização, Excluir arquivo de gravação o apaga permanentemente após confirmação. Remover uma entrada de Gravações agendadas não exclui o arquivo de mídia.

### Formato de gravação {#recording-formats}

Gravações > Formato de gravação escolhe como as gravações são salvas:

- Qualidade do provedor (cópia, MKV): o fluxo exatamente como transmitido, com todas as faixas de áudio e legendas. Mantém tudo que o provedor envia.
- Qualidade do provedor (cópia, MP4): a mesma imagem e som em um arquivo MP4, que mais dispositivos reproduzem, sem legendas e teletexto.
- Recodificação x264 (MKV ou MP4): um arquivo recodificado menor. Usa muito mais tempo de processador.
- Somente áudio (MP3 V0, FLAC, WAV, AAC M4A ou Opus): só o som, útil para rádio.

### Gravações agendadas {#scheduled-recordings}

Para gravar um programa futuro, escolha Agendar gravação sobre um programa em Exibir EPG…, No ar agora ou uma linha de programa nos resultados da pesquisa. Agendar gravação sobre um canal abre o guia dele para que você escolha primeiro o programa.

Gravações > Gravações agendadas… lista cada gravação agendada, em andamento e concluída com hora, título, canal, status e formato.

- A tecla de menu de aplicativo ou Shift+F10 sobre uma gravação abre o menu dela: Atualizar, Cancelar e Eliminar.
- Os menus de programas em View EPG e No ar agora oferecem Gravar diariamente, Gravar semanalmente e Gravar série ao lado de Agendar gravação. Enquanto o aplicativo está aberto, uma regra de série procura programas futuros com o mesmo título nesse canal. Um episódio já agendado, sendo gravado ou gravado com sucesso não é agendado novamente; o número, o título ou a descrição do episódio identifica as reprises.
- É possível selecionar mais de uma gravação; Ctrl+A seleciona todas as linhas.
- Delete ou Delete do teclado numérico pede confirmação e depois remove as gravações selecionadas. Se alguma delas ainda estiver em andamento, o programa a para primeiro.
- Escape fecha a janela.

As gravações agendadas começam sozinhas enquanto o programa está em execução, mesmo minimizado para a bandeja do sistema. A janela se atualiza sozinha ao ser aberta e sempre que uma gravação começa, termina ou é cancelada, por isso o comando Atualizar raramente é necessário.

Gravações > Limites de conexões para gravações define de 1 a 64 conexões para gravações por conta; 0 não impõe um limite adicional. Considere a reprodução e os outros dispositivos: essa opção não consulta o limite real do provedor. O agendamento verifica o pico de conexões simultâneas das gravações da mesma conta identificada. Exceder o limite requer confirmação; sem um limite conhecido, aparece o aviso habitual de sobreposição. Quando o limite é atingido, uma nova gravação é recusada e as existentes continuam. Uma gravação que usa o buffer local do reprodutor não ocupa outra conexão com o provedor. As proteções existentes para contas com um único fluxo continuam valendo.

O programa pergunta antes de fechar se ainda houver gravações agendadas esperando para começar, porque elas só começam com o programa aberto. Se você fechá-lo mesmo assim, essas gravações não vão começar.

Um arquivo não vazio, por si só, não comprova o sucesso da gravação. Capturas interrompidas recebem o estado Parcial e seus arquivos são preservados; uma parada intencional recebe o estado Interrompida pelo usuário. Episódios com falha, perdidos ou parciais podem ser agendados em uma transmissão posterior, sem repetir tentativas para a mesma transmissão. A atualização preserva a seleção múltipla e a confirmação de remoção informa quantas entradas serão removidas, mesmo quando apenas parte da lista estiver selecionada.

Se falhar o salvamento de um cancelamento, exclusão ou alteração de repetição, o agendamento anterior é preservado e aparece um erro. Uma cópia separada do arquivo ilegível é criada antes de salvar novos agendamentos. Se a cópia também falhar, as alterações são bloqueadas para proteger o original. Verifique o espaço livre e as permissões antes de reiniciar.

No Windows, Gravações > Impedir a suspensão automática durante a gravação vem ativado. Solicita que o Windows permaneça ativo durante as gravações, sem manter a tela ligada nem impedir a suspensão iniciada pelo usuário, como ao fechar a tampa de um notebook.

Reativar para gravações agendadas (Windows) vem desativado. Quando ativado, solicita um temporizador de ativação 60 segundos antes do início da próxima gravação, incluindo a margem anterior. O aplicativo deve permanecer aberto, e o hardware e as configurações de energia devem oferecer suporte a esses temporizadores. Não liga um computador desligado. Alterações e cancelamentos atualizam o temporizador; sair do aplicativo o remove.

### Margem de agendamento {#schedule-padding}

Programas raramente começam e terminam exatamente no horário. Gravações > Margem de agendamento… define quantos minutos antes de um programa uma gravação agendada começa, e quantos minutos depois do fim dela ela continua gravando. As gravações manuais não são afetadas. Os downloads de replay usam os mesmos minutos: a janela de arquivo pedida ao provedor é ampliada com eles sempre que o provedor puder atendê-la, e o download é repetido quando o arquivo chega mais curto que o programa.

### Desligar após as gravações {#shutdown-after-recordings}

Gravações > Desligar o computador quando as gravações terminarem desliga o computador quando toda gravação em andamento e agendada termina, útil para uma gravação de madrugada.

Nunca entra em ação enquanto algo ainda grava ou espera na agenda. Chegada a hora, uma janela faz contagem regressiva de 60 segundos; o foco está em Cancelar desligamento, então Enter ou Escape a para, e Desligar agora não espera. A opção se desliga sozinha depois de usada ou cancelada.

## Transmissão {#casting}

A transmissão envia um canal para uma TV ou caixa de som da sua rede: Chromecast e outros dispositivos Google Cast, caixas de som AirPlay, renderizadores DLNA e UPnP, caixas de som Sonos, reprodutores Roku e Kodi.

Arquivo > Transmitir para… procura na sua rede e lista os dispositivos encontrados, cada um seguido do seu tipo. Escolha um dispositivo e Conectar. Uma vez conectado, reproduzir um canal o envia ao dispositivo. As caixas de som, como AirPlay e Sonos, tocam o som do canal. Escolher de novo Transmitir para… desconecta.

O botão Transmitir do reprodutor integrado, Reprodutor > Transmitir / Conectar… (Ctrl+Shift+C) e Ctrl+C no reprodutor fazem o mesmo.

Para transmitir, o computador e o dispositivo precisam estar na mesma rede.

## Informações da conta {#account-info}

Arquivo > Informações da conta (Ctrl+Shift+A) mostra o estado das suas contas Xtream Codes e Stalker Portal: se a conta está ativa, a data de validade e os dias restantes, se é de teste, e quantas conexões ela permite e tem abertas. Contas encontradas em endereços de listas também são listadas.

Escolha uma conta na lista; os detalhes dela aparecem no campo de somente leitura abaixo. Atualizar pergunta ao provedor de novo, e Copiar detalhes põe os detalhes na área de transferência. As senhas nunca são mostradas.

## Opções {#options}

O menu Opções contém as configurações do programa. Cada uma é salva assim que você a muda.

- Reprodutor de mídia a usar: veja Reprodutor de mídia.
- Faixa de áudio preferida: veja Faixa de áudio preferida.
- Idioma: veja Idioma.
- Minimizar para a bandeja do sistema: veja Bandeja do sistema.
- Mostrar o reprodutor ao pressionar Enter: ligado, reproduzir um canal mostra a janela do reprodutor integrado. Desligado, a reprodução começa e o foco fica na lista de canais.
- Mostrar o URL da transmissão: adiciona o campo URL da transmissão depois da descrição do episódio na janela principal.
- Verificar atualizações automaticamente: veja Atualizações.
- Anúncios automáticos: escolha Nenhum, Somente erros, Eventos importantes ou Status detalhado para feedback automático do player e do canal. O mesmo menu ativa ou desativa separadamente três tipos de anúncios: Reprodução, Legendas e Guia.
- Atalhos de teclado: altere a combinação de teclas de um comando. Atalhos conflitantes são rejeitados; reinicie o programa após salvar.
- Configurações de exportação e configurações de importação: salve ou restaure um backup criptografado de listas de reprodução, fontes de guia, favoritos e preferências. Mantenha a senha de backup; você precisa dele para restaurar as credenciais do provedor.

### Idioma {#language}

Opções > Idioma escolhe o idioma do programa. Automático segue o do seu Windows ou desktop e usa inglês quando não há tradução para ele. A mudança se aplica completamente após reiniciar o programa.

O programa está disponível em inglês, espanhol, árabe, português do Brasil, francês, alemão, russo, turco, italiano, polonês, hindi, chinês simplificado, japonês e húngaro. Correções e novos idiomas são bem-vindos; veja Obter ajuda.

### Bandeja do sistema {#system-tray}

Quando Opções > Minimizar para a bandeja do sistema está ligado, fechar ou minimizar a janela principal a esconde na área de notificação em vez de sair, então as gravações agendadas continuam. Ative o ícone da bandeja para trazer a janela de volta. O menu dele também tem Restaurar, Controles do reprodutor, Parar gravação(ões) enquanto algo grava, e Sair. Sair usa a mesma confirmação que fechar a janela: cada gravação em espera é listada com o horário local agendado, para que você possa cancelar a saída em vez de perdê-la sem querer.

Para sair do programa por completo, use Arquivo > Sair (Ctrl+Q).

## Atualizações {#updates}

No Windows o programa pode se atualizar sozinho. Ajuda > Verificar atualizações… procura uma versão nova agora, e Opções > Verificar atualizações automaticamente verifica em segundo plano de tempos em tempos.

Quando há uma atualização disponível, você vê as novidades e é perguntado se deseja instalá-la. O download é verificado antes de qualquer instalação. A partir daí, uma única janela de atualização permanece na tela durante todo o processo: informa o que acontece em cada etapa, oferece Cancelar enquanto o download ocorre, continua visível enquanto o programa fecha e a atualização é instalada, e avisa quando a nova versão foi iniciada. Suas configurações, favoritos e gravações são mantidos.

No Linux, instale o pacote novo por cima do antigo.

Ajuda > Novidades lista as mudanças de cada versão, da mais recente para a mais antiga. Os títulos das seções estão sempre no seu idioma. As notas das três versões mais recentes aparecem no seu idioma depois de traduzidas, o que pode acontecer pouco depois do lançamento; até lá, e nas versões mais antigas, aparecem em inglês.

## Solução de problemas {#troubleshooting}

- Ajuda > Abrir pasta de registos abre a pasta com os arquivos de registro do programa, incluindo o registro das importações do guia e um registro por gravação.
- Ajuda > Copiar registo e informações de depuração copia um relatório com a versão do programa, o seu sistema e linhas de registro recentes para a área de transferência, pronto para colar em um relatório de erro. Ele contém seus endereços de transmissão, que podem incluir seu login do provedor; confira antes de compartilhar publicamente.

Problemas comuns:

- Um canal não reproduz: muitos provedores permitem só um fluxo por conta por vez. Pare outra reprodução, gravação ou transferência da mesma conta e tente de novo.
- Um canal não tem guia: confira se uma das suas fontes EPG o cobre, e importe o guia de novo.
- A reprodução engasga: o reprodutor integrado ajusta o próprio buffer. Você pode aumentar internal_player_buffer_seconds e internal_player_max_buffer_seconds no iptvclient.conf para um buffer mais paciente.
- O replay diz que o programa não está disponível: provavelmente é mais antigo que o arquivo do seu provedor.

## Atalhos de teclado {#keyboard-shortcuts}

Em qualquer lugar:

- F1: ajuda sobre o que você está usando.

Janela principal:

- Ctrl+M: Gerenciador de listas de reprodução.
- Ctrl+E: Gerenciador de EPG.
- Ctrl+I: Importar EPG para o banco de dados.
- Ctrl+W: No ar agora.
- Ctrl+Shift+A: Informações da conta.
- Ctrl+D: adicionar o canal selecionado aos favoritos, ou removê-lo.
- Delete: remover o canal selecionado dos favoritos, na categoria Favoritos.
- Ctrl+Shift+R: iniciar ou parar a gravação do canal selecionado.
- Ctrl+Shift+D: mostrar as janelas de transferência de replay.
- Ctrl+Shift+J: mostrar o reprodutor integrado.
- Ctrl+0: retorna ao canal anterior. Ctrl+H: escolha um canal assistido recentemente. Ctrl+G: insira um número de canal.
- Ctrl+Shift+I: anuncia o que está tocando agora e o próximo, incluindo o status da gravação.
- Ctrl+Shift+P: reproduzir ou pausar o reprodutor integrado.
- Ctrl+Shift+S: parar o reprodutor integrado.
- Ctrl+Shift+C: transmitir ou conectar.
- Ctrl+Acima e Ctrl+Abaixo: volume do reprodutor integrado.
- Enter: reproduzir o canal selecionado.
- Tecla de menu de aplicativo ou Shift+F10: o menu do canal.
- Ctrl+Q: sair.

Reprodutor integrado:

- Espaço: pressionar o botão com foco, como Pausar.
- Ctrl+P: reproduzir ou pausar.
- Ctrl+S: parar.
- Ctrl+R: gravar.
- S: Percorra as faixas de legenda. I: Anuncie o que está tocando. Shift+S: ler legendas em voz alta. C: ler a legenda atual. Page Up e Page Down: legendas anteriores e seguintes.
- Acima e Abaixo: volume em passos de 2%; com Ctrl, passos de 5%.
- A: próxima faixa de áudio.
- D: dispositivo de saída de áudio.
- Ctrl+C: transmitir.
- F11: tela cheia; Escape sai dela.
- Ctrl+W: ocultar o reprodutor.
- Ctrl+Q: fechar o reprodutor.

Listas de fontes no Gerenciador de listas de reprodução e no Gerenciador de EPG:

- F2: renomear.
- Delete: eliminar.

## Obter ajuda {#support}

Perguntas, relatórios de erro e notícias de versões:

- O grupo do Telegram SerrebiProjects: https://t.me/SerrebiProjects
- Relatórios de erro e sugestões no GitHub: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Ajuda > Sobre… mostra a versão em uso e linka ambos. Ao relatar um problema, Ajuda > Copiar registo e informações de depuração dá os detalhes necessários para rastreá-lo.

## Ferramentas pessoais {#personal-tools}

Mantenha o aplicativo aberto para gravações agendadas, lembretes e alertas de pesquisas salvas. Lembretes e alertas de pesquisa não reativam o computador. As gravações podem solicitar um temporizador de ativação no Windows se a opção descrita em Gravações agendadas estiver ativada.

- Gravações > Agendar por horário funciona sem guia. Introduza a hora local como AAAA-MM-DD HH:MM e escolha a ocorrência na mudança de hora. Editar horários altera uma gravação pendente ou o fim de uma em curso. Confirme conflitos de conexão conforme Gravações agendadas; duração máxima de sete dias.
- Na reprodução a pedido, Ctrl+Left/Right salta 10 segundos, Ctrl+Shift+Left/Right 60 segundos, Ctrl+T abre a escolha do instante e T anuncia o tempo decorrido, total e restante. Os atalhos são configuráveis. O fluxo deve permitir saltos e ter duração conhecida; a reprodução em direto não muda.
- Ver > Listas de favoritos gere até 50 listas com nome e 2000 canais por lista, separadas dos favoritos existentes. Selecione um canal antes de abrir a janela para o adicionar. Mover para cima/baixo ou Ctrl+Up/Down altera a ordem. Canais ausentes ficam na lista, mas só podem ser reproduzidos quando regressarem.
- Ver > Pesquisas de programas guardadas guarda até 30 pesquisas em títulos ou descrições, em todos os canais, no selecionado ou numa cópia dos canais de uma lista de favoritos. Após importar o guia e a cada 15 minutos pesquisa os próximos 14 dias. Cada pesquisa mostra até 500 resultados; restrinja pesquisas truncadas. As definições de anúncios controlam os novos resultados, que permitem criar lembretes ou gravações.
- A exportação encriptada inclui agendamentos, lembretes e histórico de pesquisa, sem ficheiros multimédia. A importação mostra quantos elementos substituirá e fecha a aplicação; volte a abri-la para terminar. Termine antes gravações e transferências. Gravações passadas ou já iniciadas não reiniciam. Cópias antigas só substituem definições e mantêm agendamentos e lembretes locais.

Exibir > Histórico de notificações mantém as últimas 200 notificações enfileiradas na sessão atual. Selecione uma entrada para ler Detalhes; Atualizar recarrega a lista e Copiar detalhes copia o texto. Credenciais reconhecíveis em URLs e linhas de autenticação são ocultadas no histórico e no texto copiado. Isso não garante que qualquer mensagem esteja livre de dados privados. Limpar histórico pede confirmação. O histórico é descartado ao fechar o aplicativo; os arquivos de log existentes não são alterados.
