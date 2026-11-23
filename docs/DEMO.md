# Five-minute project demo

Сценарий помогает показать проект без хаотичного перехода по файлам. Windows/WSL2
стенд уже проверен; шаги ниже можно выполнить как воспроизводимую демонстрацию.

## Before the demo

- использовать отдельную dev/staging базу и новые credentials;
- проверить `/health` и `/ready`;
- подготовить безопасный публичный или синтетический пример;
- открыть Swagger UI, worker terminal и `parser_jobs`;
- не показывать `.env` или старую историю с credentials.

## 0:00–0:40 — Problem

> Crycon исследует публичные Web3-профили, сохраняет evidence и рассчитывает
> объяснимый confidence score. Score показывает силу совпадения, но не является
> доказательством личности.

Показать первый экран README и архитектурную схему.

## 0:40–1:30 — API contract

В `/docs` показать раздельные `/health` и `/ready`, пагинацию, evidence endpoint,
typed payload для `/jobs` и ответ `202 Accepted`. Главная мысль: API описывает
контракт, но не выполняет discovery внутри HTTP request.

## 1:30–2:40 — Durable job

Поставить job с `Idempotency-Key`, затем повторить запрос. Ожидается один job ID и
переход `queued → running → completed`. Объяснить: idempotency защищает от повторной
отправки, lease — от двух worker, завершающих одну задачу.

## 2:40–3:30 — Evidence and scoring

```bash
python search_candidate.py --id 44
python recalculate_scores.py --id 44 --explain
```

Breakdown объясняет результат. Формула имеет имя policy; изменение весов создаёт
новую версию, тесты и отдельный план пересчёта данных.

## 3:30–4:20 — PostgreSQL decisions

Открыть миграции `003–005` и объяснить три проблемы: stale/duplicate search,
частичные discovery writes и ненадёжный lifecycle фоновых задач. Важны инварианты,
а не объём SQL.

## 4:20–5:00 — Tests and honest limits

```bash
python -m pytest -q
```

Сообщить проверенный результат: 140 passed, включая десять PostgreSQL tests.
Честно назвать следующий шаг: deployment, staging negative-access test и
`EXPLAIN ANALYZE` на реалистичном объёме.

## If Docker is unavailable

Показать README/Mermaid, OpenAPI contract через тесты, unit test run, CI workflow
и объяснение миграций. Не нужно изображать непроверенную production-готовность:
точная граница между реализованным и проверенным — часть инженерной зрелости.

## Questions to expect

- Почему PostgreSQL jobs, а не Celery/RabbitMQ?
- Как избежать двух worker на одной задаче?
- Почему repository не содержит все CRUD-операции?
- Как не сломать старую score formula?
- Почему `/health` не проверяет базу, а `/ready` проверяет?
- Почему materialized view удалена, а не исправлена?
- Что будет при падении worker до `complete`?

Основания решений: [ARCHITECTURE.md](ARCHITECTURE.md).
