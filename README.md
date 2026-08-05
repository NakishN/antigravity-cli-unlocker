# Antigravity CLI Unlocker v3.0

🚀 **Antigravity CLI Unlocker v3.0** — современный кроссплатформенный инструментарий для обхода региональных ограничений при работе с **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на Linux, macOS и Windows.

---

## 💡 Что нового в версии 3.0?

1. **Split-Tunnel Micro-Proxy (Локальный раздельный прокси):**
   - **Защита сессий:** Сервисы авторизации (`accounts.google.com`, `oauth2.googleapis.com`) обрабатываются **напрямую (DIRECT)** без изменений трафика.
   - **Изоляция:** Переменные `HTTP_PROXY` / `HTTPS_PROXY` выставляются **только для дочернего процесса `agy`** в режиме `run-wrapped`. Не требуются права `root` / администратора и изменение глобальных сетевых настроек ОС!
2. **Безопасный сигнатурный патчер:**
   - **Версионный реестр (`versions.json`):** Проверка точных SHA-256 хэшей бинарников с офсетами замен.
   - **Wildcard Pattern Matching:** Умный поиск по байтовым маскам для неизвестных версий `agy`.
   - **Атомарная запись:** Бэкап `*.original.bak` перед изменениями и проверка совпадения размера байт-в-байт.
3. **Релизы в один клик (.AppImage, .exe):**
   - **Linux:** Доступны `.AppImage` пакеты и бинарники `antigravity-unlock-linux-x86_64`.
   - **Windows:** Доступны готовые `.exe` исполняемые файлы (без необходимости установки Python).

---

## 📦 Быстрый запуск

### Вариант 1: Использование готовых релизов (Рекомендуется)

Скачайте бинарник для вашей ОС в разделе **[Releases](https://github.com/NakishN/antigravity-cli-unlocker/releases)**:

#### Linux (.AppImage)
```bash
chmod +x Antigravity_Unlocker-x86_64.AppImage
./Antigravity_Unlocker-x86_64.AppImage run -- agy login
```

#### Windows (.exe)
Запустите в консоли PowerShell / CMD:
```cmd
antigravity-unlock.exe run -- agy login
```

---

### Вариант 2: Запуск из исходников (Python 3.8+)

Клонируйте репозиторий и установите CLI:

```bash
git clone https://github.com/NakishN/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker
pip install .
```

---

## 🛠 Команды CLI

### 1. Запуск agy под локальным прокси (Run-Wrapped)
Запускает локальный Split-Tunnel прокси на случайном порту, изолированно настраивает окружение и исполняет `agy`:
```bash
antigravity-unlock run -- agy login
antigravity-unlock run -- agy generate "напиши функцию на python"
```

### 2. Патчинг бинарного файла agy
Автоматически сканирует PATH, VS Code / Cursor расширения и директории Antigravity IDE, подготавливая бинарник:
```bash
antigravity-unlock patch
```

### 3. Восстановление исходного файла
Восстанавливает оригинальный бинарный файл `agy` из `.bak` бэкапа:
```bash
antigravity-unlock restore
```

### 4. Автономный запуск прокси-сервера
Запускает локальный прокси на порту 18888 (или любом указанном):
```bash
antigravity-unlock proxy --port 18888
```

### 5. Проверка статуса
```bash
antigravity-unlock status
```

---

## 🔐 Безопасность и архитектура

```
+----------------------------------------------------------------+
|                   Процесс agy / Antigravity                    |
+----------------------------------------------------------------+
                               |
                   [Local Split-Tunnel Proxy]
                               |
        +----------------------+----------------------+
        |                                             |
[accounts.google.com]                       [generativelanguage]
        |                                             |
   (DIRECT connection)                        (Smart Endpoint)
```

- **Принцип наименьших привилегий:** Программа работает без прав суперпользователя.
- **Никаких фальшивых сертификатов:** Не требуется установка CA-сертификатов.

---

## 🧪 Тестирование

Для прогона встроенных тестов выполняйте:
```bash
python3 -m unittest discover tests
```

---

## 📄 Лицензия

Открытая лицензия [MIT](LICENSE).
