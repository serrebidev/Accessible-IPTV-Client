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

Os canais favoritos são marcados com "(Favorito)", e cada linha também nomeia o programa no ar quando o guia o tem. Quando uma pesquisa também encontrou programas, suas linhas nomeiam o programa e o canal em que ele passa.

### Descrição do episódio e URL da transmissão {#episode-description}

Tab a partir da lista de canais chega à Descrição do episódio: o programa no ar no canal destacado, com seus horários e descrição, e o que vem a seguir. Shift+Tab volta direto para a lista de canais. O texto segue o canal destacado.

Quando Opções > Mostrar o URL da transmissão está ligado, o campo URL da transmissão vem um Tab depois. Ele mostra o endereço do canal, o que ajuda ao relatar um problema. A maioria o deixa desligado.

## Favoritos {#favorites}

Os favoritos mantêm em um só lugar os canais que você mais assiste. Pressione Ctrl+D em um canal, use o menu dele, ou Exibir > Adicionar aos favoritos. Os favoritos aparecem na categoria Favoritos perto do começo da lista de categorias, e Exibir > Ir para os favoritos leva você até lá.

Para remover um favorito, pressione Ctrl+D nele de novo, ou pressione Delete na categoria Favoritos.

Os favoritos são guardados por provedor e canal, não por endereço de transmissão, então sobrevivem a uma atualização da lista. Nada da sua conta é guardado com eles.

## Vídeo sob demanda {#video-on-demand}

Exibir > Vídeo sob demanda (filmes && séries) troca a lista de categorias dos canais ao vivo para os filmes e as séries do seu provedor. As categorias se chamam Movies ou Series seguidos da categoria do provedor. Escolher uma série lista seus episódios em ordem de temporada e episódio. Pressione Enter para reproduzir um filme ou um episódio.

Exibir > TV ao vivo && Replay volta aos canais ao vivo. O campo de pesquisa é esvaziado ao trocar.

O vídeo sob demanda funciona melhor com contas Xtream Codes, que descrevem bem o catálogo delas. Para listas M3U simples, o programa reconhece filmes e séries pelos nomes dos grupos e pela numeração dos episódios.

## Gerenciador de listas de reprodução {#playlist-manager}

Arquivo > Gerenciador de listas de reprodução (Ctrl+M) lista suas fontes de listas de reprodução. Ele abre com o foco na lista.

- Adicionar arquivo: uma lista M3U ou M3U8 no seu computador.
- Adicionar URL: o endereço da Internet de uma lista M3U.
- Adicionar Xtream Codes: uma conta Xtream Codes.
- Adicionar Stalker Portal: uma conta de portal Stalker (MAG).

Sobre uma fonte da lista, a tecla de menu de aplicativo ou Shift+F10 abre o menu dela: Copiar URL, Renomear (F2) e Eliminar (Delete). Um nome que você dá a uma fonte é só um rótulo; ele não muda a fonte.

Escolha OK para manter suas mudanças, ou Cancelar para descartá-las. Os canais recarregam depois de OK.

### Contas Xtream Codes {#xtream-codes}

Uma conta Xtream Codes precisa do endereço do servidor, do seu nome de usuário e da sua senha, que seu provedor fornece. O nome é o seu próprio rótulo para a conta. Deixe "Adicionar automaticamente a URL do XMLTV" marcada para adicionar o guia do provedor ao Gerenciador de EPG ao mesmo tempo.

Contas Xtream Codes também lhe dão vídeo sob demanda, replay quando o provedor oferece, e o estado da conta em Arquivo > Informações da conta.

### Contas Stalker Portal {#stalker-portal}

Uma conta Stalker Portal precisa do endereço do portal e do endereço MAC que seu provedor registrou para você. Alguns portais também pedem usuário e senha. "MAC aleatório" inventa um novo endereço MAC, útil apenas quando o provedor pede para você escolher um. "Tentar adicionar o XMLTV do provedor" adiciona o guia do portal quando ele tem um.

## Guia de programação (EPG) {#epg}

O guia de programação, ou EPG, diz o que passa em cada canal agora e depois. Ele vem de arquivos XMLTV publicados pelo seu provedor ou por outra fonte. O programa os importa para um banco de dados local, e o usa para a descrição do episódio, No ar agora, Exibir EPG…, listas de replay e pesquisas.

### Gerenciador de EPG {#epg-manager}

Arquivo > Gerenciador de EPG (Ctrl+E) lista suas fontes de guia.

- Adicionar arquivo: um arquivo XMLTV no seu computador (.xml ou .xml.gz).
- Adicionar URL: o endereço da Internet de um guia XMLTV.

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
- D: escolher o dispositivo de saída de áudio.
- Ctrl+C: transmitir para um dispositivo.
- F11: tela cheia ligada ou desligada. Escape sai dela.
- Ctrl+W: ocultar a janela do reprodutor; a reprodução continua.
- Ctrl+Q: fechar o reprodutor e parar a reprodução.

Os mesmos comandos estão no menu Reprodução do reprodutor. O reprodutor se reconecta sozinho quando um fluxo ao vivo cai, e mantém a faixa de áudio que você escolheu.

### Faixas de áudio {#audio-tracks}

Canais podem carregar várias faixas de áudio, como outros idiomas ou audiodescrição. Pressione A para ir à próxima faixa, use Reprodução > Faixa de áudio, ou Tab até Escolher faixa de áudio, que sempre nomeia a faixa em reprodução.

Uma faixa que você escolhe é lembrada para aquele canal e volta na próxima vez. Para escolhê-las automaticamente, veja Faixa de áudio preferida.

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

Gravar o que você está assistindo no reprodutor integrado usa a mesma conexão com o provedor, então funciona mesmo com contas que permitem só um fluxo por vez.

Parar uma gravação pode levar um momento enquanto o arquivo é concluído. Fechar o programa deixa as gravações em andamento concluírem seus arquivos por conta própria.

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
- Eliminar remove a gravação destacada da lista; uma em andamento é parada primeiro, depois de perguntar.
- Escape fecha a janela.

As gravações agendadas começam sozinhas enquanto o programa está em execução, mesmo minimizado para a bandeja do sistema.

### Margem de agendamento {#schedule-padding}

Programas raramente começam e terminam exatamente no horário. Gravações > Margem de agendamento… define quantos minutos antes de um programa uma gravação agendada começa, e quantos minutos depois do fim dela ela continua gravando. As gravações manuais não são afetadas.

### Desligar após as gravações {#shutdown-after-recordings}

Gravações > Desligar o computador quando as gravações terminarem desliga o computador quando toda gravação em andamento e agendada termina, útil para uma gravação de madrugada.

Nunca entra em ação enquanto algo ainda grava ou espera na agenda. Chegada a hora, uma janela faz contagem regressiva de 60 segundos; o foco está em Cancelar desligamento, então Enter ou Escape a para, e Desligar agora não espera. A opção se desliga sozinha depois de usada ou cancelada.

## Transmissão {#casting}

A transmissão envia um canal para uma TV ou caixa de som da sua rede: dispositivos Chromecast, renderizadores DLNA e UPnP, e dispositivos AirPlay como Apple TV e HomePod.

Arquivo > Transmitir para… procura na sua rede e lista os dispositivos encontrados. Escolha um dispositivo e Conectar. Alguns dispositivos AirPlay precisam primeiro de Emparelhar…, que pede o código mostrado na TV. Uma vez conectado, reproduzir um canal o envia ao dispositivo. Escolher de novo Transmitir para… desconecta.

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

### Idioma {#language}

Opções > Idioma escolhe o idioma do programa. Automático segue o do seu Windows ou desktop e usa inglês quando não há tradução para ele. A mudança se aplica completamente após reiniciar o programa.

O programa está disponível em inglês, espanhol, árabe, português do Brasil, francês, alemão, russo, turco, italiano, polonês, hindi, chinês simplificado, japonês e húngaro. Correções e novos idiomas são bem-vindos; veja Obter ajuda.

### Bandeja do sistema {#system-tray}

Quando Opções > Minimizar para a bandeja do sistema está ligado, fechar ou minimizar a janela principal a esconde na área de notificação em vez de sair, então as gravações agendadas continuam. Ative o ícone da bandeja para trazer a janela de volta. O menu dele também tem Restaurar, Controles do reprodutor, Parar gravação(ões) enquanto algo grava, e Sair.

Para sair do programa por completo, use Arquivo > Sair (Ctrl+Q).

## Atualizações {#updates}

No Windows o programa pode se atualizar sozinho. Ajuda > Verificar atualizações… procura uma versão nova agora, e Opções > Verificar atualizações automaticamente verifica em segundo plano de tempos em tempos.

Quando há uma atualização, você é avisado do que há de novo e perguntado se quer instalá-la. O download é verificado antes de qualquer coisa ser instalada. O programa se fecha durante a atualização e reinicia sozinho ao terminar, depois diz se deu certo. Suas configurações, favoritos e gravações são mantidos.

No Linux, instale o pacote novo por cima do antigo.

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
