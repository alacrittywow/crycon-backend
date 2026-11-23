# Аудит Crycon и foundation, 20 ноября 2026

## Область и база сравнения

Изучены все Python/SQL-модули, runtime/dependencies, отслеживаемые пути и вся
доступная Git-история: 6 коммитов, checkout не shallow. HEAD `f8f120b` совпал с
публичным HEAD, проверенным через `git ls-remote`. Рабочая ветка:
`codex/security-foundation`. До этой работы checkout уже содержал незавершённый
вынос discovery scoring, тесты, README/CI и staged удаления IDE/cache. Они были
проверены и продолжены; reset, commit, push и переписывание истории не выполнялись.

История:

1. `b9b8a05`: весь исходный MVP, .env, IDE и bytecode попали в Git.
2. `652a3e5`: добавлен IDE VCS config; runtime Python/SQL не изменился.
3. `14d3369`: pg_trgm, materialized view, aliases и замена поиска в CLI/боте;
   новые функции БД ошибочно вложены в finish_parser_job.
4. `0e7a4e0`: функции поиска вынесены на уровень модуля.
5. `b71ad39`: Python 3.11.11 для Railway, изменение .env.
6. `f8f120b`: вопреки сообщению «Удалён .env», добавлен только .gitignore;
   .env остался отслеживаемым во всех 6 версиях.

Исторические значения секретов проверялись без вывода содержимого: только наличие
и названия переменных. Никакие найденные ключи не использовались.

## Поток данных

1. Discovery читает KEYWORDS/SOURCES; GitHub users/repos → owners → user profiles,
   Discourse search → posts → user JSON. Локальные лимиты и sleep, без очереди.
2. db_supabase ищет exact (platform, username). Если профиля нет, последовательно
   вставляет candidate, profile, evidence. Discovery score вычисляется из текста.
   parser_jobs охватывает только discovery: running → done/failed.
3. Enrichment читает кандидатов и profiles, HTML/profile/source URLs, GitHub API,
   последние README. Извлекает контакты, EVM/Solana/ENS/.sol; сохраняет evidence;
   обновляет score собственной формулой enrichment-v1.
4. Resolver строит варианты X/ENS/Lens/Farcaster/кошелька, запрашивает Web3.bio,
   дедуплицирует ответы. Exact X link даёт confidence 95, handle reuse 55,
   известный тип identity 90, иной handle 60. Создаёт/находит candidate и пишет
   profiles/contacts/wallets/evidence. Это не криптографическое подтверждение.
5. Deep scan читает GitHub profile/README/FUNDING и Discourse JSON/search/posts,
   извлекает кошельки с контекстом; пишет wallets/evidence, не пересчитывает score.
6. Recalculation читает candidate/profiles/contacts/wallets, фильтрует контакты,
   считает recalculation-v1 и обновляет candidate. Relevance остаётся прежним.
7. CLI и Telegram читают карточки, evidence, top и общий поиск. Bot resolve
   запускает resolver и recalculation subprocess; затем читает результат из БД.

## Границы побочных эффектов

| Модуль | Сеть / чтение БД | Запись БД | Чистые операции |
|---|---|---|---|
| parse_web3_to_supabase | request_json, github_search_*, discourse_get_user_profile, discourse_search_forum | save_record_to_supabase и main через db_supabase | clean_text (схлопывает whitespace), normalize_base_url, формирование headers |
| db_supabase | get_supabase_client создаёт SDK client; find_existing_profile, search_candidate_ids выполняют запросы | insert_candidate_with_profile_and_evidence, create_parser_job, finish_parser_job | импортированные clean_text, discovery scoring, status; refresh_search_view после 003 — совместимый no-op |
| enrich_to_supabase | fetch_text/fetch_json, collect_github_text; get_candidates_to_enrich/get_candidate_by_id/get_profiles_for_candidate, *_exists | insert_contact/insert_wallet/insert_evidence/update_candidate_scores; save_artifacts_for_candidate/enrich_candidate/main оркестрируют | regex extraction, URL/contact/context helpers, merge/empty_artifacts, Base58 |
| resolve_identity | request_json/fetch_web3bio_profiles, find_candidate_by_x_handle/fetch_candidate, *_exists | create/ensure_candidate, insert_profile/contact/wallet/evidence, save_profile_artifacts/resolve_identity | input normalization, query construction, profile links/wallet mapping, confidence_for_profile |
| wallet_deep_enrich | request_json, github_fetch_*, collect_github/discourse_*, fetch_candidates/fetch_candidate_by_id/fetch_profiles, wallet_exists | insert_wallet_and_evidence/insert_wallets_from_sources/deep_enrich_candidate | strings_from_any, context checks, Base58/extract_wallets, decode_github_content, discourse URL parsing |
| recalculate_scores | fetch_candidates/fetch_candidate_by_id/fetch_profiles/fetch_contacts/fetch_wallets | update_candidate/recalculate_candidate/main | imported contact filtering, calculate_scores, status_from_overall |
| search_candidate | fetch_*, get_top_candidates, print_candidate_card/main | нет | short и часть форматирования; print пишет stdout |
| bot | fetch_*, get_top_candidate_ids; Telegram replies/polling | resolve subprocess вызывает пишущие скрипты | esc/short/chunk_text/parse_candidate_id_from_resolve_output; format_* также читают БД |
| test_supabase_connection | main читает parser_jobs | main вставляет connection_test | нет; это ручной integration script |

polite_sleep блокирует выполнение; CLI print-функции имеют stdout side effect.
config читает файл/окружение, но не сеть. Чистые модули src/crycon не импортируют
Supabase, requests, config или корневые CLI.

## Находки по приоритету

### P0: секреты и доступ

.env отслеживался в HEAD и истории: Supabase, GitHub, Web3.bio, Telegram.
Учитывать все значения как скомпрометированные, даже если они уже истекли.
Foundation удаляет файл из текущего index/working tree, не удаляет его из HEAD
и истории без нового коммита/отдельной очистки. Ротация не выполнена; инструкция
в SECURITY.md. Два ignore-файла (у одного пробел в конце), IDE/cache были в Git.

В SQL нет ENABLE ROW LEVEL SECURITY или policies. Это не доказывает фактическое
состояние deployed Supabase: dashboard grants/RLS не проверялись. Telegram не
ограничивает вызывающих /resolve и /resolve_full; они могут запускать платные/
длительные сетевые операции и запись. Перед публичным сервисом нужны auth/quotas.

### P1: корректность данных и confidence

- ~~Вставка candidate/profile/evidence раздельная, без транзакции/компенсации~~ —
  исправлено миграцией 004 и одним транзакционным RPC с advisory lock.
- profiles UNIQUE(platform, username) глобальный и case-sensitive; поиск existing
  exact. Контакты UNIQUE(contact_type,value) глобальные, но *_exists проверяет
  candidate_id: при общем контакте вставка может нарушить unique.
- Wallet uniqueness не содержит candidate_id/chain, а nullable address/name_service
  допускают дубли с NULL; скрипты обычно пишут пустые строки, что даёт другую
  семантику. Общий кошелёк может вызвать конфликт между кандидатами.
- Evidence повторяется при resolver rerun; при duplicate contact/wallet enrichment
  пропускает и новый evidence. Нет модели отдельного независимого подтверждения.
- Resolver не ищет существующего кандидата по ENS/кошельку при отсутствии X;
  username match и ILIKE substring X-contact могут ошибочно выбрать другого.
- Enrichment объединяет тексты нескольких URL и затем сохраняет один evidence_url
  для всех artifacts. Это может приписать источник неверно.
- Deep Discourse topic допускает exact post другого автора; кошелёк в README/HTML
  может принадлежать проекту или третьему лицу. SSRF/redirect и ограничения объёма
  скачивания не обеспечены для произвольных сохранённых URL; обрезка идёт после загрузки.
- Две формулы score, details в SCORING.md. Число profile rows не измеряет независимость,
  presence кошелька не равно подтверждению владения. Высокие константы confidence
  не калиброваны; например пустой кандидат после пересчёта имеет overall=25.
- Исходная дедупликация Web3.bio lowercased Base58: исправлено foundation, с тестом.

### P1: PostgreSQL / поиск

`schema_v1.sql`:

- PK bigserial и FK ON DELETE CASCADE есть. Почти все child candidate_id nullable;
  нет CHECK 0–100, ограничений status, непустого username, непустого кошелька.
- updated_at имеет только default, не обновляется автоматически; finished_at jobs
  не заполняется finish_parser_job. result_count также без CHECK.
- Есть lower(username/value/address/name_service) B-tree и platform index, evidence
  candidate_id index. Exact `.eq` по raw колонкам не соответствует lower expression
  index; `%query%` ILIKE требует trigram, не обычного B-tree.
- Нет candidate_id indexes у profiles/contacts/wallets/known_aliases, важных для
  карточек/cascade/join; нет индекса сортировки overall_trust_score.

`002_search_improvements.sql`:

- pg_trgm, GIN по поисковым полям и отдельный многоколоночный GIN на view есть.
- Несколько LEFT JOIN дают произведение количества profiles × contacts × wallets
  кандидата. RPC возвращает повторные candidate_id и применяет LIMIT до дедупликации.
- bio входит в view/index, но отсутствует в similarity/WHERE fuzzy функции.
- Нет tie-breaker для равного rank; similarity threshold зависит от PostgreSQL
  setting. LIMIT не валидирован в SQL/Python.
- CREATE MATERIALIZED VIEW не идемпотентен. Нет UNIQUE index, подходящего для
  CONCURRENTLY refresh; candidate_id здесь и не уникален из-за JOIN.
- В состоянии 002 view не обновляется pipeline. Прежний refresh_search_view использует
  отсутствующий в Supabase Client `client.sql`. Миграция 003 удаляет view и делает
  helper совместимым no-op, устраняя необходимость refresh.
- Данные MV могут устаревать после insert/update/delete; exact search иногда маскирует
  это. RPC ошибки поглощаются, но отсутствие known_aliases падает до fuzzy fallback.
- Значения query прямо подставляются в PostgREST `.or_` grammar; запятые/скобки и
  wildcard `%/_` требуют отдельного контракта экранирования. Это не raw SQL injection,
  но возможны ошибки фильтра/неожиданно широкий поиск.
- Exact search возвращает только одну строку без порядка, даже при нескольких match.

SQL проверен статически. Миграции, планы EXPLAIN, фактические RLS/grants, нагрузка,
collation и версия deployed PostgreSQL не проверены и не изменены.

### P2: связанность, сопровождение, тесты

CRUD/read helpers повторяются в пяти скриптах; network wrappers и regex/context
фильтры отличаются между enrichment/deep scan. В is_probably_personal_website
после return True есть недостижимый блок. Пока не удалён: не относится к foundation.
`search_candidate --id --full` не передаёт full в print_candidate_card.
Bot смешивает async и blocking reads, парсит stdout subprocess вместо typed result;
relative paths зависят от cwd, timeout/nonzero exit не оформлены в устойчивый job result,
HTML chunks могут разрезать тег. Нет retry/backoff с учётом Retry-After, pagination,
job resume/cancellation, structured metrics. broad except скрывает причины ошибок.

До foundation в Git не было pytest/CI, был ручной пишущий connection script;
в найденном checkout имелись 5 незавершённых discovery/status tests. Foundation
покрывает чистый core и адаптеры, но не объявляет весь pipeline протестированным.

## Сделано в foundation

- src/crycon package, editable install, pyproject/requirements-dev, Python 3.11 CI;
- одна конфигурация python-dotenv, без мутации процесса и repr секретов;
- обе чистые score policy и discovery breakdown, CLI --explain;
- общая нормализация/Base58, вынесена стабильная дедупликация с исправлением регистра;
- офлайн scoring/normalization/dedup/config/adapter/CLI tests и network guard;
- безопасный .env.example, единый .gitignore; staged removals .env, typo ignore,
  ранее подготовленные removals .idea/bytecode сохранены; отслеживаемых CSV не найдено;
- README, AGENTS, audit, scoring contract, rotation/history procedure.

SQL не менялся, новые сервисы не добавлялись. Корневые entry points и полезные
импортируемые helpers сохранены. pandas удалён из dependencies после проверки
всех imports/callers: код его не использует.

## Проверки и непроверенное

На Python 3.11: compile, pytest, pip check. Отдельно проведено 3 000 differential
сравнений трёх формул с изолированными функциями исторического HEAD на
детерминированных синтетических входах: совпадение всех результатов.
Старые .env не загружались; Supabase/Telegram/Web3.bio/GitHub API pipeline не запускался.
Точный итоговый test count и список файлов — в отчёте проверки рядом с deliverables.
GitHub Actions подготовлен, но remote workflow не запускался (push запрещён).

Непокрытые области: планы и нагрузка fuzzy SQL на объёме production, гонки в
остальных enrichment-потоках, реальные API shapes/rate limits, авторство evidence,
полнота extraction, Telegram lifecycle,
subprocess timeouts, auth/RLS, end-to-end job recovery, реальная ротация секретов.

## Короткий план следующих итераций

1. P0 вне кода: ротация всех старых credentials, аудит доступа; история только
   отдельным явно разрешённым шагом.
2. ~~Маленький P1 code step поиска~~ выполнен 20 ноября 2026: миграция 003 удаляет
   materialized view, считает rank по живым таблицам один раз на candidate,
   добавляет deterministic tie-break и FK indexes. Добавлены fake-client и локальные
   PostgreSQL 16 integration-тесты. Реальная база не изменялась.
3. ~~Маленький P1 code step целостности discovery~~ выполнен 20 ноября 2026:
   миграция 004 объединяет candidate/profile/evidence в одну транзакцию, закрывает
   гонку дублей и проверяет новые значения на уровне БД. Реальная база не изменялась.
4. ~~Ввести repository interface только для существующих операций чтения~~ выполнено
   20 ноября 2026: protocol, Supabase adapter, reusable fake и совместимые legacy
   wrappers без изменения CLI.
5. ~~FastAPI service layer~~ выполнен 20 ноября 2026: read-only endpoints для
   liveness, pagination, search, candidate detail и evidence; OpenAPI и fake-backed
   tests. `/health` отделён от readiness. Auth всё ещё нужен до публикации.
6. ~~Durable parser jobs и discovery worker~~ выполнены 20 ноября 2026: migration
   005, idempotent enqueue, SKIP LOCKED lease, heartbeat, retry/exhaustion, stale
   recovery, API POST/GET jobs и one-shot worker. Enrichment handlers ещё не перенесены.
7. ~~Перевести enrichment и bot subprocess на typed job handlers~~ выполнено
   21 ноября 2026: discriminated payloads, общий registry/worker, bot enqueue и /job.
8. Dockerfile и Compose source готовы для API/worker и test PostgreSQL; YAML проверен,
   но image build не выполнялся из-за отсутствия Docker CLI в среде.
9. Score v2 — отдельная задача с размеченными fixtures и явными правилами
   независимости источников, конфликтов и повторного вычисления stored scores.

## Результат этапа поиска

`003_live_unique_search.sql` сначала удаляет зависимую функцию 002, затем старый
materialized view и создаёт `search_candidates_fuzzy` как SQL STABLE function над
базовыми таблицами. Совпадения из candidates/profiles/contacts/wallets объединяются
через UNION ALL, затем группируются по candidate_id с максимальным rank. Поэтому
кандидат появляется не более одного раза, а прежние GIN indexes остаются доступны
простым веткам запроса. Поиск
включает main_username, display_name, bio, profile username, contact value,
wallet address и name service. Сортировка: rank DESC, candidate_id ASC.

Limit с NULL использует 10, остальные значения ограничены 1–100. Пустой query
возвращает пустой набор. Добавлены индексы candidate_id для profiles, contacts,
wallets и known_aliases; прежние GIN trigram indexes 002 остаются на базовых полях.
Python-клиент дополнительно удаляет дубли RPC для совместимости во время rollout,
когда база ещё может оставаться на 002. Старый `refresh_search_view` — no-op.

Integration fixture применяет цепочку `schema_v1 → 002 → 003` в случайной схеме.
Тест сначала воспроизводит stale snapshot 002 и 8 строк для кандидата из JOIN
2 profiles × 2 contacts × 2 wallets, затем проверяет живой уникальный результат.
Также проверены update без refresh, равный rank с tie-break, bio, limit=0,
пустой query, наличие FK indexes и повторное применение 003. Локальный прогон:
PostgreSQL 16.16, 102 passed. Supabase и production не использовались.

## Результат этапа целостности хранения

`004_storage_integrity.sql` заменяет три независимые REST-вставки discovery одной
функцией PostgreSQL. Candidate, profile и evidence создаются внутри одной транзакции:
если любой шаг завершается ошибкой, предыдущие вставки откатываются. Это устраняет
частично сохранённых кандидатов, которые раньше могли появиться при сетевой ошибке
между запросами.

Повторная находка того же `platform/username` возвращает существующего кандидата.
Сравнение не зависит от регистра, а transaction-level advisory lock закрывает гонку,
когда два worker одновременно проверили отсутствие профиля. Lock ограничен одной
нормализованной парой и не сериализует весь discovery pipeline.

Ограничения scores, confidence, result_count и статусов добавлены как `NOT VALID`.
PostgreSQL сразу проверяет новые и изменяемые строки, но миграция не падает из-за
исторических некорректных записей. Старую некорректную строку нельзя изменить, пока
она не исправлена; очистку истории и последующий `VALIDATE CONSTRAINT` следует делать
отдельным контролируемым этапом. Trigger обновляет `candidates.updated_at`, а адаптер
теперь заполняет `parser_jobs.finished_at` при завершении job.

Integration fixture применяет цепочку `schema_v1 → 002 → 003 → 004` и проверяет
rollback на последнем шаге, повторную находку без дубля, case-insensitive lookup,
новые ограничения, совместимость с исторической некорректной строкой, updated_at и
идемпотентность миграции. Полный локальный прогон: PostgreSQL 16.16, 106 passed.
Supabase и production не использовались.

## Результат этапа repository interface

Добавлен `CandidateRepository` — небольшой контракт только для уже существующих
операций чтения. Код, который показывает карточку кандидата, больше не обязан знать
о цепочках Supabase `.table().select()`: эти детали находятся в
`SupabaseCandidateRepository`. Старые функции CLI, Telegram bot, resolver,
recalculation и wallet enrichment оставлены как совместимые обёртки, поэтому
пользовательские команды и импорты не изменились.

Fake repository хранит синтетические записи в памяти и реализует тот же контракт.
Это подготовка к API: endpoint-тест сможет подставить fake и проверить HTTP-логику
без credentials, сети и Supabase. Специфичные записи и pipeline-выборки намеренно не
обобщались, чтобы слой не стал универсальной копией SDK.

Добавлены три unit-теста repository: структурная замена fake, перевод чтений в
Supabase-вызовы с ограничением limit и отсутствие запроса для пустого поиска.
Полный локальный прогон на одноразовом UTF-8 PostgreSQL 16.16: 109 passed. Кластер
остановлен и удалён; реальная база и Supabase не использовались.

## Результат этапа read-only FastAPI

Добавлен factory `create_app(repository)` и production-приложение `crycon.api:app`.
Repository внедряется зависимостью: тест передаёт in-memory fake, а Supabase client
создаётся лениво только при data-запросе. Поэтому import, генерация OpenAPI и
`GET /health` работают без `.env`, сети и БД.

API включает страницу candidates с ограниченными limit/offset, поиск с batch-fetch
результатов без N+1, detail с profiles/contacts/wallets и отдельный evidence resource.
Path/query bounds проверяются FastAPI; отсутствующий кандидат возвращает 404.
Evidence вынесен отдельно, чтобы тяжёлая история не раздувала каждую карточку.
HTTP query больше не подставляется в raw PostgREST `.or_()` filter: wallet address
и name service проверяются отдельными параметризованными eq/ilike-вызовами.

Пять ASGI-тестов проверяют liveness, пагинацию, поиск, validation, 404, detail,
evidence и отсутствие write-методов в OpenAPI. Они используют актуальный httpx
ASGI transport без сетевого сервера и без deprecated TestClient. Полный прогон на
одноразовом PostgreSQL 16.16: 115 passed; офлайн: 109 passed, 6 skipped. Кластер
остановлен и удалён. Реальная база, Supabase, deploy и push не использовались.

Перед внешней публикацией остаются auth/permissions, quotas/rate limits, CORS policy,
RLS-аудит и отдельный readiness check с коротким безопасным repository ping.

## Результат этапа durable parser jobs

`005_parser_job_lifecycle.sql` расширяет parser_jobs полями idempotency key, attempts,
lease owner, heartbeat, error и timestamps. `enqueue_parser_job` сериализует одинаковый
job type/key advisory lock и возвращает существующую job. `claim_parser_job` выбирает
одну запись через `FOR UPDATE SKIP LOCKED`, поэтому параллельные workers не получают
одну задачу. Завершить, продлить или вернуть job может только владелец lease.

Просроченный heartbeat при следующем claim возвращает job в очередь, пока не исчерпан
max_attempts; после этого job становится failed. Retryable ошибка сохраняет безопасное
сообщение и ставит повтор, неизвестная Python-ошибка записывает только имя exception
класса и пробрасывается supervisor — её текст может содержать credential.

API получил `POST /jobs` с обязательным `Idempotency-Key`, а также `GET /jobs` и
`GET /jobs/{id}`. Поддерживается только discovery: несуществующие handlers нельзя
поставить в очередь. `parse_web3_to_supabase.py --worker-only` забирает одну queued
job, выполняет query из самой записи и отправляет heartbeat между порциями работы.
Обычный режим сначала enqueue-ит manual job, затем работает тем же worker policy.

Три PostgreSQL integration-теста проверяют duplicate enqueue, единственного владельца,
защиту complete/heartbeat, retry exhaustion, stale recovery и повторное применение
005. Unit/ASGI-тесты проверяют adapter, безопасную error policy и job endpoints.
Полный прогон PostgreSQL 16.16: 125 passed; офлайн: 116 passed, 9 skipped. Кластер
остановлен и удалён; real Supabase, внешние API, deploy и push не использовались.

## Результат финальной сборки backend

Добавлены discriminated Pydantic payloads для discovery, contact enrichment, wallet
enrichment, score recalculation и identity resolution. Общий registry отклоняет
неизвестный job type и вызывает существующие Python services напрямую. Telegram bot
больше не запускает subprocess и не парсит stdout: `/resolve` enqueue-ит typed job,
а `/job` показывает состояние. Identity handler после resolution вызывает score
recalculation тем же процессом.

Общий `worker.py` умеет one-shot и polling loop. SIGTERM/SIGINT прекращают получение
новых задач; неизвестная ошибка уже переведена lifecycle в failed и в лог выводится
только класс exception. Discovery отправляет heartbeat между порциями, остальные
handlers — до и после операции; для них stale timeout worker по умолчанию увеличен
до 15 минут.

FastAPI получил настоящий `/ready` с storage ping. Все job endpoints защищены
constant-time сравнением `X-API-Key`; если `CRYCON_ADMIN_API_KEY` не задан, job admin
закрыт по умолчанию. Candidate endpoints остаются read-only.

Подготовлены multi-purpose Dockerfile, `.dockerignore` и Compose: API привязан к
localhost, worker запускается loop mode, PostgreSQL 16 доступен отдельным integration
profile. Compose YAML разобран локальным YAML parser. Docker CLI отсутствует, поэтому
image build, container healthcheck и Compose runtime остаются непроверенными.

Итоговый прогон на одноразовом PostgreSQL 16.16: 133 passed; офлайн: 124 passed,
9 skipped. Кластер остановлен и удалён. Реальные Supabase/API, Telegram polling,
Docker runtime, deploy и push не запускались.

### Windows/WSL2 verification, 23 ноября 2026

После исходного аудита Docker runtime проверен на Windows, WSL2 и Ubuntu 26.04:
API image собран, Compose healthcheck и Swagger отвечают, `/health` возвращает 200,
а containerized PostgreSQL 16 suite завершился результатом 133 passed. Smoke-test
обнаружил, что отсутствие Supabase credentials давало 500 на `/ready`: storage
dependency создавалась до защищённого тела endpoint. Dependency resolution перенесён
в readiness boundary, добавлен regression-тест; теперь ожидаемо возвращается 503.

Первый Docker integration run также показал, что глобальный DNS guard блокировал
имя `postgres-test`. Guard ограничен unit-тестами, а Compose получил отдельный test
target/service с явным test database URL. Реальная Supabase и внешние API не открывались.

### Staging verification, 23 ноября 2026

Создан отдельный Supabase staging с новыми credentials. Миграции применены по
порядку до `006`; RLS включён на storage-таблицах, anon/authenticated grants и
публичный RPC EXECUTE сняты, backend secret сохранил readiness/read access.

Через атомарную discovery RPC создан только синтетический candidate. FastAPI
поставил score recalculation job, worker забрал её, пересчитал score и завершил с
result_count=1. Повторный Idempotency-Key вернул прежнюю job; после restart worker
обработал новую job. Реальные discovery/enrichment API не вызывались.

Добавлены безопасные JSON events worker: start, idle, finish, failure и stop.
Поля, похожие на token/secret/key/query/payload/message, запрещены контрактом.
Финальный локальный прогон: 130 offline tests; полный PostgreSQL 16.16 — 140 passed.

Справка: [PostgreSQL materialized views](https://www.postgresql.org/docs/current/rules-materializedviews.html)
подтверждает, что данные MV требуют refresh и могут быть неактуальны.
