# Radar Público

MVP Python/FastAPI para `@Log_pmdf_bot`. Comandos públicos em conversa privada: `/start`, `/ajuda`, `/pncp`, `/compras`, `/cancelar`, `/pncp termo`, `/licitacoes termo` e `/atas termo`.

`/pncp` e `/compras` abrem submenus com **Licitações**, **Atas** e **Pesquisa**. Após escolher o botão, envie o termo em texto livre. A seleção fica no Firestore por 10 minutos e sobrevive a reinícios. `/cancelar` encerra. Pesquisa combina contratações e atas da fonte selecionada; não compara preços. Veja [fluxo e validação](docs/MENUS.md).

As buscas consultam uma **amostra** do PNCP dos últimos sete dias, filtrada localmente pelo objeto: até duas páginas de 50 registros por modalidade (6, 8, 4, 5), ou duas páginas de atas por atualização global. Até cinco resultados. Ausência na amostra não comprova inexistência. Atas podem estar vencidas/canceladas; confirme vigência e possibilidade de adesão na fonte oficial.

Limites distribuídos: 10 consultas por usuário em qualquer intervalo de 60 minutos, 1.500 atualizações aceitas/dia UTC e 400 chamadas PNCP/dia UTC. Cache de 30 minutos, em até 256 documentos Firestore. Duplicatas recentes não repetem consultas. Falhas na persistência bloqueiam novas buscas.

Briefing diário sem IA paga: busca notícias publicadas nos últimos sete dias e envia até cinco novidades ainda não publicadas no canal `@logisticapmdf`, todos os dias a partir de 09h de Brasília (o agendamento GitHub pode atrasar). Coletores para TCU, Compras, PNCP, Tesouro Nacional, Fazenda, Gestão e Agência Brasil; cada fonte indisponível é identificada no boletim. O texto traz título e trecho oficiais, fonte/data/link e um ponto de atenção editorial, sem inventar obrigações legais. Histórico de URLs no Firestore evita repetição entre dias; uma falha na coleta não é apresentada como ausência de notícias. Veja [fontes, validação e operação](docs/AUTOMATIC_BRIEFING.md).

Testes locais (Python 3.12 em CI; validação local também em 3.13):

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -q
```

Não há dependência nem chamada de IA paga. Não coloque tokens no Git. O contêiner usa usuário sem privilégios. Alterações de produção exigem confirmação do responsável.

- [Implantação e IAM](docs/DEPLOY.md)
- [Limites e acesso público](docs/PUBLIC_ACCESS.md)
- [Riscos financeiros e operação](docs/COSTS.md)
- [Validação e pendências](docs/VALIDATION.md)
