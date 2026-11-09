# Запуск на VPS без Cloudflare

Серверный пакет подготовлен для первоначального запуска на одном Linux VPS. Это не подтверждение работающего публичного сервиса: нужны VPS, домен, DNS, приватный токен бота, резервирование и проверка на телефонах. Обычный локальный compose.yaml менять не нужно. Не объединяйте его с compose.production.yaml.

Для небольшого пилота ориентир — Ubuntu 24.04 LTS, 2 vCPU, 4 ГБ RAM и SSD от 40 ГБ; реальное потребление зависит от видео. Хранилище должно расширяться. Нужны Docker Engine с Compose v2, Git и Python3. Устанавливайте Docker по официальной инструкции для вашей ОС. Node/Python-зависимости и FFmpeg устанавливаются внутри образов.

## Первый запуск

1. Создайте DNS A-запись поддомена приложения на IPv4 сервера. AAAA добавляйте только при работающем IPv6. Откройте TCP 80 и 443; SSH оставьте доступным для администрирования. База, Redis и API не публикуют свои порты. Caddy сам получает и обновляет сертификат, когда DNS указывает на сервер и порты доступны. Домен и доступ к VPS оплачиваются отдельно.
2. Клонируйте maloymedika82/catfeedik на сервер и перейдите в каталог. Не переносите локальную тестовую базу и пользовательскую .env в production.
3. Выполняйте команды по одной:

```sh
python3 scripts/init-production.py
```

```sh
nano .env.production
```

Файл создаётся с правами 0600 и случайным паролем БД; повторный запуск его не перезаписывает. Заполните:

- APP_DOMAIN: только полное имя хоста, например app.your-domain.ru, без https:// и путей.
- TELEGRAM_BOT_TOKEN: действующий токен @animalfeedikbot, только приватно на сервере.
- MAX_VIDEO_BYTES: явно подтверждённый предел размера видео. Локальное тестовое значение — 20971520 байт; для публичного запуска проверьте его отдельно. Прокси допускает максимум 24 MB на запрос. Точный GPS не используется: пользователь выбирает город, сервер хранит только центр города.
- OWNER_TELEGRAM_IDS: 2022054034, если это ваш Telegram ID.
- AI_API_KEY / AI_MODEL: только если провайдер проверен. Можно оставить ключ пустым; AI_MODERATION_ENABLED=0 включает первоначальную ручную проверку. Сохранённый выбор Owner в админке имеет приоритет над этой начальной настройкой.

Для AI сначала выполните `docker compose --env-file .env.production -f compose.production.yaml -f compose.funnel.yaml run --rm --no-deps -T api python scripts/check-ai.py`: проверка посылает два маленьких тестовых изображения и не начисляет поинты. Для VPS без Funnel уберите второй `-f`. Только после успешного vision-теста включайте `AI_MODERATION_ENABLED=1` и перезапускайте API, Worker и Beat. Если владелец уже выключил AI в админке, его сохранённый выбор имеет приоритет. Не отправляйте ключ в чат.

POSTGRES_PASSWORD сгенерирован скриптом; не меняйте его после создания базы без отдельной смены пароля в PostgreSQL. Не отправляйте содержимое .env.production в чат, скриншоты или GitHub. Compose подставляет пароль в URL, поэтому для него используйте только сгенерированный hex либо URL-безопасные символы.

```sh
docker compose --env-file .env.production -f compose.production.yaml config --quiet
```

```sh
docker compose --env-file .env.production -f compose.production.yaml up -d --build
```

```sh
docker compose --env-file .env.production -f compose.production.yaml ps
```

```sh
curl --fail https://app.your-domain.ru/api/health
```

Замените домен своим. API должен вернуть status=ok и database=postgresql. Запуск API проверяет production-настройки; тестовые входы принудительно выключены. Worker и Beat ждут здорового API. Видео находятся в отдельном Docker volume, а не в статической раздаче. /docs и /openapi.json снаружи закрыты. Деньги выключены.

## Подключение Telegram

Production Compose запускает отдельный сервис `bot`: он отвечает на `/start` и `/help` в личном чате и показывает кнопку Mini App. Один раз после сборки API задайте имя, описание, команды и кнопку меню через `docker compose --env-file .env.production -f compose.production.yaml -f compose.funnel.yaml run --rm --no-deps -T api python -m backend.bot --configure` (для VPS с Funnel). Бот использует long polling и отдельный том для позиции очереди; существующий webhook должен быть отключён. Фоновый сервис не трогает кормления и видео.

### Вариант для VPS за NAT без выделенного IP

Если провайдер не направляет публичные TCP 80/443 на VPS, можно использовать Tailscale Funnel. Он выдаёт постоянный публичный HTTPS-адрес вида `https://имя-сервера.имя-сети.ts.net` без собственного домена. Нужен аккаунт Tailscale, включённые MagicDNS, HTTPS и Funnel; у Funnel есть ограничения полосы пропускания, поэтому проверьте загрузку и просмотр видео под ожидаемой нагрузкой. Внешний адрес зависит от сохранения устройства в аккаунте и работы Tailscale. Подробности: https://tailscale.com/docs/features/tailscale-funnel.

На сервере с уже установленным Tailscale используйте `tailscale up --hostname=catfeedik-test` и откройте выданную ссылку входа в своём браузере. Для локального HTTP-входа применяйте оба Compose-файла:

```sh
docker compose --env-file .env.production -f compose.production.yaml -f compose.funnel.yaml up -d --build
curl --fail http://127.0.0.1:8080/api/health
tailscale funnel --bg --yes 8080
tailscale funnel status
```

Compose-override публикует веб-сервис только на `127.0.0.1:8080`; Tailscale выдаёт внешний HTTPS. При каждом последующем обновлении используйте оба Compose-файла. Сначала проверьте публичный HTTPS, затем укажите полученный адрес в Telegram. Не включайте одновременно старую публикацию Caddy на 80/443 через один только `compose.production.yaml`.

В @BotFather выберите /mybots → @animalfeedikbot → Bot Settings → Menu Button → Configure menu button. Укажите HTTPS-адрес приложения и подпись «Открыть приложение». Откройте бота и нажмите эту кнопку. Это проверенный сервером Telegram-вход; открытие URL в обычном браузере не выдаёт роль Owner.

Для проверки Owner нажмите «Открыть админпанель» в приложении после входа. Сессия хранится в sessionStorage, отдельная вкладка может её не получить. Перед публичным запуском проверьте на Android и iOS запись, GPS, загрузку, просмотр видео, профиль, модерацию и задания. Никакого webhook для открытия меню не требуется; обработчик сообщений бота пока не реализован.

## Обновление и данные

Перед обновлениями делайте резервную копию PostgreSQL и video volume на отдельное хранилище и проверяйте восстановление на изолированном сервере. Docker volumes и перезапуск контейнера не заменяют резервную копию. Redis/Celery — очередь, решения и начисления хранятся в БД. Для текущего пилота на VPS доступен скрипт:

```sh
python3 scripts/backup-production.py --restore-test
```

Для ежедневного проверенного снимка на VPS установите `deploy/catfeedik-backup.service` и `deploy/catfeedik-backup.timer` в `/etc/systemd/system`, выполните `systemctl daemon-reload` и `systemctl enable --now catfeedik-backup.timer`. Проверяйте `systemctl status catfeedik-backup.timer` и `journalctl -u catfeedik-backup.service`. Таймер создаёт копии только на VPS, не удаляет старые снимки и не заменяет отдельное внешнее хранилище; следите за заполнением диска.

Он сначала снимает согласованный дамп PostgreSQL, затем архивирует неизменяемые видео, пропуская незавершённые файлы в `_incoming`. Контрольные суммы проверяются, а дамп восстанавливается в отдельную временную базу на том же PostgreSQL и удаляется после проверки. Копия создаётся в `/var/backups/catfeedik` с закрытыми правами; **её обязательно нужно скопировать вне VPS**. Это не заменяет проверку восстановления на другом сервере и не обеспечивает автоматическое резервирование. Храните скопированные архивы конфиденциально: они содержат персональные данные и видео. Перед изменениями схемы или крупным обновлением повторяйте копирование вне сервера.

Не запускайте down -v: это удаляет тома с данными. Обычный перезапуск с сохранением данных:

```sh
docker compose --env-file .env.production -f compose.production.yaml restart
```

После резервной копии обновите исходники через `git pull --ff-only` и соберите новый образ API. Версия схемы контролируется Alembic: на совершенно пустой БД API применит начальную миграцию сам, а на существующей БД с несовпадающей версией откажется запускаться. Перед переключением API на новую версию применяйте подготовленные миграции отдельно:

```sh
docker compose --env-file .env.production -f compose.production.yaml -f compose.funnel.yaml build api
docker compose --env-file .env.production -f compose.production.yaml -f compose.funnel.yaml run --rm --no-deps -T --entrypoint alembic api upgrade head
docker compose --env-file .env.production -f compose.production.yaml -f compose.funnel.yaml up -d --no-build
```

Для VPS без Funnel уберите `-f compose.funnel.yaml`. Перед миграцией проверьте её SQL и восстановимую резервную копию. Существующая пилотная БД была сверена со схемой и отмечена начальной версией `45778a076fab` без пересоздания таблиц. Мониторинг, ограничения частоты запросов, автоматические резервные копии и политика хранения остаются отдельными задачами до открытого массового запуска.

## Проверка пакета без публикации

Для технической проверки на Linux с Docker Compose 2.24.4+ можно собрать `catfeedik-api:local` через `docker build -f deploy/Dockerfile.api -t catfeedik-api:local .` и `catfeedik-web:local` через `docker build -f deploy/Dockerfile.web -t catfeedik-web:local .`, затем запустить `python3 scripts/check-production.py`. Нужен созданный .env.production. Скрипт использует отдельное случайное имя Compose, новую БД, тестовый токен и пустой AI-ключ, временный HTTP-порт 127.0.0.1:18081. Он удаляет только собственные тестовые тома в конце. Это проверка контейнеров и отключения dev-входов; она не получает публичный сертификат и не проверяет настоящий Telegram.
