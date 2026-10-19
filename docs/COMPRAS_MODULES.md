# Módulos e filtros Compras.gov.br

No Telegram: Menu principal → Compras.gov.br → categoria. PNCP e comandos
anteriores continuam funcionando. Sem novos serviços, segredos ou campos de
sessão. Seleção individual continua válida por 10 minutos.

## Novos módulos oficiais

| Botão | Endpoint após https://dadosabertos.compras.gov.br | Entrada |
|---|---|---|
| Itens e resultados | /modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133 | Descrição |
| Preços de materiais | /modulo-pesquisa-preco/1_consultarMaterial | Código CATMAT |
| Preços de serviços | /modulo-pesquisa-preco/3_consultarServico | Código CATSER |
| Contratos | /modulo-contratos/1_consultarContratos | Descrição e órgão |
| Planejamento | /modulo-pgc/1_consultarPgcDetalhe | Descrição, órgão e ano PCA |

Itens mostram código de catálogo, unidade, quantidade, estimativa, resultado,
fornecedor e situação quando presentes. Estimativa sigilosa é identificada.
Preços mostram registros individuais com unidade, capacidade, quantidade e data;
não calculam médias nem afirmam equivalência ou conformidade de pesquisa de preços.
Contratos mostram fornecedor, valor global e vigência, excluindo contratos marcados
como excluídos. Planejamento não garante publicação ou contratação futura.
Valores ausentes/inválidos são identificados; zero é preservado.
Links são gerados para PNCP ou consulta oficial da API, nunca a partir de URLs
arbitrárias da resposta.

## Filtros

Escolha o módulo por botão e envie, substituindo os códigos pelos códigos oficiais:

```text
Licitações: viaturas | dias=30 | uf=DF | orgao=CODIGO | uasg=CODIGO
Atas / Pesquisa / Itens: viaturas | dias=30 | uasg=CODIGO
Preços: CODIGO_CATALOGO | dias=90 | uf=DF | orgao=CODIGO | uasg=CODIGO
Contratos: viaturas | orgao=CODIGO | dias=90
Planejamento: viaturas | orgao=CODIGO | ano=2027
```

Filtros são opcionais, exceto órgão em contratos/planejamento. Não usar CNPJ no
lugar do código do órgão. O botão Como filtrar apresenta essas instruções sem
apagar a seleção. Filtros valem só para a mensagem atual, sem persistência adicional.

- Padrão 7 dias; de 1 a 90 dias incluindo hoje em Brasília.
- Licitações por publicação, itens por inclusão, preços por data da compra;
  atas/contratos por início de vigência. Não significa todos os registros vigentes.
- PCA usa ano, padrão atual; aceita 2020 até atual + 2. Não aceita dias.
- UF é enviada à API em licitações e preços. Não é suportada nos demais módulos.
- Órgão é enviado à API em licitações, contratos e PCA. Em preços, filtro local
  pelo codigoOrgao na amostra. Atas/Pesquisa/Itens aceitam UASG, não órgão.
- UASG é enviada ao parâmetro específico de cada módulo.
- Opções inválidas, duplicadas ou não suportadas geram orientação antes de
  consumir quota de consultas ou chamar APIs. Navegação ainda conta como update.
- Estes filtros não se aplicam aos menus PNCP.

## Paginação e custos

Até 2 páginas de 50 por endpoint/modalidade; até 5 resultados exibidos.
Máximo de chamadas por busca: Licitações 6; Atas 2; Pesquisa 12;
cada novo módulo 2. Para na última página ou página vazia. Cada chamada reserva
o orçamento compartilhado antes de acessar a API. HTTP 429 interrompe sem retry;
falhas não geram cache parcial. Prazo global continua 30 segundos.
Limites globais/usuário permanecem iguais; mais páginas consomem o orçamento
diário mais rápido. Não garante abrangência nem custo zero. Filtro textual local.

Cache v2 por fonte, módulo, termo normalizado, filtros canônicos e dia, incluindo
ano PCA. Filtros em ordem diferente compartilham cache; filtros diferentes não.
Cache anterior de uma página não é reutilizado.

## Validação

173 testes aprovados e 1 ignorado (emulador Firestore), Python 3.13, 19/10/2026.
Cobrem parâmetros, segunda página, limites, deduplicação, valores, validação
antecipada, cache, navegação e comandos anteriores.
Cinco chamadas públicas pequenas (uma por novo módulo) responderam HTTP 200 com
envelope esperado, mas sem registros na amostra. Isso não valida conteúdo real
ou preços; conferência de registros e interface no Telegram pendente após deploy.

Especificação consultada em 19/10/2026:
https://dadosabertos.compras.gov.br/v3/api-docs
e https://dadosabertos.compras.gov.br/swagger-ui/index.html .
