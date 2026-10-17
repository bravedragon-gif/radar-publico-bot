# Radar Público

MVP Python/FastAPI para `@Log_pmdf_bot`. Comandos públicos em conversa privada: `/start`, `/ajuda`, `/pncp termo`, `/licitacoes termo` e `/atas termo`.

As buscas consultam uma **amostra** do PNCP dos últimos sete dias, filtrada localmente pelo objeto: até duas páginas de 50 registros por modalidade (6, 8, 4, 5), ou duas páginas de atas por atualização global. Até cinco resultados. Ausência na amostra não comprova inexistência. Atas podem estar vencidas/canceladas; confirme vigência e possibilidade de adesão na fonte oficial.

Limites distribuídos: 10 consultas por usuário em qualquer intervalo de 60 minutos, 1.500 atualizações aceitas/dia UTC e 400 chamadas PNCP/dia UTC. Cache de 30 minutos, em até 256 documentos Firestore. Duplicatas recentes não repetem consultas. Falhas na persistência bloqueiam novas buscas.

Briefing sem IA: seleção determinística de cinco títulos originais, recentes e relevantes, com fonte oficial, data e confirmação na página. Gera JSON/texto para revisão. Cron e publicação automática permanecem desativados. As fontes de Gestão/Compras redirecionaram para login na validação de 17/10/2026; **a geração real ainda está bloqueada**.

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
