# Формулы score: сохранённое поведение v1

Foundation переносит расчёты из HEAD `f8f120b` в чистый модуль. Формулы не исправлялись
под видом рефакторинга. Score — эвристика, не вероятность и не доказательство личности.

## Discovery: `discovery-v1`

Текст: username + display_name + bio + matched_keyword + source, в нижнем регистре.
Каждая из подстрок validator, governance, delegate, dao, defi, protocol, staking,
solana, ethereum, web3, grant, proposal добавляет 10 один раз.
GitHub +20; source, начинающийся с discourse, +25; непустые bio/profile_url/source_url
по +10. Каждая из подстрок scam, malware, drained, recovery, guaranteed profit,
airdrop scam вычитает 40. Результат ограничен 0–100.

Сохранены особенности: одинаковые profile_url и source_url дают два бонуса;
matched_keyword сам добавляет баллы; `airdrop scam` получает два штрафа
(`scam` и `airdrop scam`); matching по подстроке, а не по границе слова.
Discovery записывает identity=50, wallet=contact=0 и overall=relevance.
Resolver создаёт кандидата с отдельными константами relevance=40, overall=45,
identity=50 и status=needs_review; это не новая общая формула.

`explain_relevance_score` возвращает `version`, `signals` с положительными и
отрицательными points, `raw_score`, `clamp_adjustment`, `score`.
Сумма points + clamp_adjustment равна score.

## Итоговый score: две существовавшие policy

В обоих вариантах:

- identity baseline=50; от 2 строк profiles +15; от 3 строк +10;
- source trust baseline=50; GitHub +15; Discourse +15;
- wallet score = максимальный confidence кошельков, минимум 0;
- overall = int(0.4 × relevance + 0.3 × identity + 0.2 × source trust +
  0.1 × max(contact score, wallet score)); int отбрасывает дробную часть.

| Различие | `enrichment-v1` | `recalculation-v1` |
|---|---|---|
| Контактный бонус identity | +10 при любом confidence ≥70 | +10 при любом полезном контакте, даже с низким confidence |
| Кошельки в identity | нет бонуса | +5 при наличии любой строки |
| Contact score | максимум всех confidence, минимум 0 | максимум полезных контактов, минимум 0 |
| Регистр platform | исходный | strip/lower |
| Ограничение overall | отсутствует в прежнем коде | 0–100 |

Пример: relevance=40, profiles=[], schema.org website confidence=90,
wallet confidence=85. Enrichment: identity=60, contact=90, overall=53.
Recalculation: identity=55, contact=0, overall=51. Пересчёт после enrichment
может менять score без появления новых данных: это существующее поведение.

Полезность контактов сохраняет фильтры прежнего recalculate_scores.py:
email, X, LinkedIn, GitHub и личные сайты; служебные URL/ассеты, форумные URL,
ссылки на уже сохранённый профиль/источник исключаются. Lens/Farcaster пока не входят.
Фильтры подстрок несовершенны; это также не менялось.

Статусы для обоих вариантов и discovery: <40 weak; 40–59 needs_review;
60–79 valid; ≥80 strong. Формулы не валидируют диапазоны входных confidence;
в enrichment некорректные входы могут дать overall>100. Исправление требует
новой policy и согласованного пересчёта, а не незаметного clamp.

`explain_scores` возвращает policy version, scores, identity/source signals,
число принятых/отброшенных контактов, max confidence, взвешенные overall terms,
поправки округления и clamp. `calculate_scores` и `calculate_enrichment_scores`
возвращают только прежние 5 полей БД. Breakdown вычисляется по запросу, не хранится.

## Что foundation меняет явно

Scoring не меняется. Конфигурация унифицирована: process env всегда имеет приоритет,
пустые числовые параметры используют defaults, `.env` привязан к editable checkout,
интерполяция отключена. Старый бот и ручной smoke script раньше перезаписывали env.

Дедупликация Web3.bio сохраняет первый результат и порядок, platform/обычные
identity сравнивает без учёта регистра, EVM address — без учёта регистра.
Solana/Base58 address и Solana identity сохраняют регистр: прежнее `.lower()`
могло склеить разные идентификаторы. Это отдельное исправление с regression-тестом.
Кандидаты между платформами автоматически не объединяются.

## Что не следует заключать из score

Число строк profiles не доказывает независимость источников. Ссылки одного Web3.bio
ответа также не обязательно независимы. Контакты, кошельки и text matches ещё
могут относиться к третьим лицам. v2 должна учитывать происхождение и независимость
evidence, отрицательные сигналы и конфликтующие связи; для неё нужен отдельный
набор размеченных примеров, сравнение результатов v1/v2 и решение о пересчёте.
