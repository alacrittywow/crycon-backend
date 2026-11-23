# Roadmap

Roadmap построен по снижению рисков, а не по количеству технологий. Каждый этап
имеет проверяемый результат.

## Current state

- [x] pure scoring, normalization and deduplication core;
- [x] repository boundary and reusable fake;
- [x] typed FastAPI API;
- [x] durable PostgreSQL jobs and typed worker;
- [x] live unique fuzzy search and atomic discovery migrations;
- [x] offline and PostgreSQL integration tests;
- [x] Dockerfile, Compose and CI source;
- [x] Docker API build, healthcheck and full test suite on Windows/WSL2;
- [ ] worker runtime/restart verification;
- [x] isolated Supabase staging, RLS and safe worker smoke test;
- [ ] public frontend.

## 1 — Reproducible Windows/WSL2 runtime

- собрать API и worker images без локального Python;
- запустить `postgres-test` и integration suite;
- проверить healthcheck, worker shutdown и restart;
- уточнить README по результатам реального запуска.

**Done:** чистый checkout поднимается по инструкции, тесты проходят, containers
не требуют ручных исправлений внутри image.

## 2 — Safe staging Supabase

- [x] создать отдельный staging project и новые credentials;
- [x] применить миграции `schema_v1 → 006`;
- [x] проверить RPC через Supabase SDK;
- [x] настроить RLS/grants и backend access;
- [x] выполнить API/worker/idempotency/restart smoke test;
- [ ] проверить anon-denial отдельным HTTP-тестом и stale job recovery на staging.

**Done:** staging отделён от production, credentials не в Git, права подтверждены
не только успешными, но и запрещёнными запросами.

## 3 — Observability and operational safety

- structured logs с `job_id`, `candidate_id`, source и duration;
- метрики очереди и внешних API;
- timeout, bounded response и retry с `Retry-After`;
- quotas для job API и allowlist Telegram users;
- correlation ID от enqueue до completion.

**Done:** по ошибке можно найти job, handler, источник и attempts без вывода secrets.

## 4 — Search and scoring quality

- размеченные fixtures: match, weak match, conflict;
- правила независимости источников и конфликтов;
- `scoring-v2` без изменения v1 задним числом;
- precision/recall на fixtures;
- `EXPLAIN ANALYZE` на production-like dataset.

**Done:** веса объясняются примерами, метрики воспроизводимы, миграция stored scores
имеет отдельный план.

## 5 — Portfolio frontend

- React/TypeScript client по OpenAPI contract;
- search, candidate card, evidence timeline и score breakdown;
- loading/empty/error states;
- подписи «confidence, not proof»;
- публичный read model с allowlist полей;
- e2e happy path на staging.

**Done:** пользователь понимает происхождение score; frontend не получает admin
controls или закрытые поля.

## 6 — Release hygiene

- отозвать исторические credentials;
- отдельно согласовать очистку Git-истории;
- выбрать лицензию;
- включить branch protection и обязательный CI;
- записать короткий demo после готовности UI.

**Done:** secret scanning не находит действующих ключей, CI обязателен, лицензия
выбрана владельцем, README ведёт к воспроизводимой демонстрации.

## Deliberately postponed

- Kubernetes до измеренной потребности;
- message broker до ограничений PostgreSQL queue;
- микросервисы до независимых нагрузочных границ;
- ML score без размеченных данных;
- автоматическая запись тестов в реальную базу.

Это сознательно отложено: сейчас такие шаги увеличили бы сложность быстрее, чем
надёжность или ценность портфолио.
