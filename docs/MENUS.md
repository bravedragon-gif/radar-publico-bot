# Menus PNCP e Compras.gov.br

## Uso

1. Iniciar a conversa com `/start` (ou abrir com `/menu`).
2. Tocar em **PNCP** ou **Compras.gov.br** no menu principal.
3. Escolher **Licitações**, **Atas** ou **Pesquisa** no teclado de resposta.
4. Digitar o termo, por exemplo `viaturas`.

Depois de iniciar, a navegação funciona por botões: **Voltar ao PNCP/Compras.gov.br**,
**Menu principal**, **Cancelar** e **Ajuda**. Os teclados são persistentes e continuam
disponíveis após os resultados. Apenas os termos de busca precisam ser digitados.
Voltar, trocar de fonte, abrir o menu principal ou cancelar limpa a seleção anterior.
Ajuda preserva a seleção e apresenta os botões das fontes. `/start` também limpa a
seleção. Os comandos `/pncp`, `/compras`, `/cancelar` e atalhos de busca continuam
disponíveis. Os textos exatos dos botões de navegação são reservados; para buscar
esses termos, use um comando direto, por exemplo `/pncp PNCP`.

Os botões incluem o nome da fonte para evitar ambiguidade. A seleção vale por
10 minutos, é individual e persiste no documento de usuário já existente no
Firestore. **Cancelar** ou `/cancelar` remove a seleção. O texto pesquisado não é salvo na sessão.
Atalhos anteriores continuam disponíveis. `/compras termo` consulta contratações;
para busca geral, selecionar Pesquisa no menu. Texto sem seleção válida recebe
orientação para abrir um menu. Não há interpretação por IA.

Pesquisa significa busca geral por termo em contratações e atas. Não significa
pesquisa de preços, nem levantamento exaustivo.

## Fontes, escopo e limites

- PNCP: submenu Licitações usa modalidades PNCP 6, 4 e 5, até duas páginas por
  modalidade. Atas usa atualização global, até duas páginas. Pesquisa combina a
  busca anterior de contratações (6, 8, 4, 5) com atas, até 10 páginas no total.
  Os comandos diretos antigos preservam seu escopo.
- Compras.gov.br: API pública de produção `https://dadosabertos.compras.gov.br`.
  Contratações: `/modulo-contratacoes/1_consultarContratacoes_PNCP_14133`, com
  `dataPublicacaoPncpInicial`, `dataPublicacaoPncpFinal`, `codigoModalidade`,
  `pagina=1`, `tamanhoPagina=50`. Licitações usa códigos SIASG 3, 4 e 5; Pesquisa
  inclui 6 e 7. A resposta histórica confirmou que código SIASG 5 corresponde ao
  código PNCP 6 (pregão eletrônico); os códigos não são intercambiáveis.
- Atas Compras: `/modulo-arp/1_consultarARP`, `dataVigenciaInicialMin/Max`, uma
  página de 50. Filtra início de vigência, não atualização, assinatura ou toda a
  vigência. Atas excluídas são descartadas; estar na amostra não garante adesão.
- Janela de sete dias; filtro textual local pelo objeto. Até cinco resultados
  no conjunto. Na Pesquisa, atas e contratações compartilham esse limite.
- Cache por fonte, categoria, termo normalizado e dia; validade de 30 minutos.
- Mesma quota compartilhada de 10 consultas/60 minutos, mesmo teto de 400 chamadas
  externas/dia e 1.500 updates/dia UTC. Navegação conta como update, não consulta.
- Busca Compras usa até 3 chamadas em Licitações, 1 em Atas e 6 em Pesquisa.
  Todas as chamadas reservam orçamento antes de acessar a fonte.
- Prazo total de busca de 30 segundos. HTTP 429 interrompe sem retry e persiste
  pausa independente por fonte. Ajuda/cache não dependem dessa pausa.
- Teclados de resposta usam apenas updates `message`; não exigem mudar webhook,
  configurar callbacks ou acessar tokens para esta implementação.

## Custos e implantação

Nenhum serviço, segredo, permissão IAM ou dependência foi criado para os menus.
Cada seleção/limpeza faz uma escrita adicional no documento existente; texto livre
faz uma leitura para recuperar a seleção. Expiração é lógica, sem TTL faturável.
O volume extra de Firestore, consultas, logs e novas imagens/builds pode gerar
cobranças. Os limites são operacionais, não garantias de custo zero.

Esta alteração não foi implantada. Revisar o PR antes de integrar à main e autorizar
a implantação somente no Radar. O workflow `deploy-cloud-run.yml` usa acionamento
manual (`workflow_dispatch`) na main. Não alterar o serviço `dodfpmdfbot`.

## Validação

Validação local dos botões em 19/10/2026: 124 testes aprovados e 1 ignorado
(emulador Firestore). Dois avisos de depreciação das dependências e um aviso de
permissão do cache do pytest no ambiente local. Inclui fluxo completo por botões
nas seis combinações de fonte/categoria, ajuda, voltar, cancelar, menu principal,
entrada inválida, expiração e duplicatas. A interface real no Telegram ainda
precisa de validação após implantação autorizada.
Testes cobrem menus, sessão, expiração, cancelamento, isolamento por usuário,
seleção da fonte, quota, cache por fonte, parâmetros oficiais, paginação limitada,
vazio, falhas HTTP e bloqueios independentes após 429.

Consultas públicas reais em 18/10/2026: uma página de atas filtrada por `registro`
retornou dois registros com links oficiais; uma consulta histórica de contratações
confirmou a codificação de modalidades. Isso não valida o Telegram nem o acesso
do Cloud Run à nova API; ambos exigem validação após implantação autorizada.

Documentação oficial: https://dadosabertos.compras.gov.br/swagger-ui/index.html
e https://dadosabertos.compras.gov.br/v3/api-docs .

Teclado de resposta do Telegram: https://core.telegram.org/bots/api#replykeyboardmarkup .
