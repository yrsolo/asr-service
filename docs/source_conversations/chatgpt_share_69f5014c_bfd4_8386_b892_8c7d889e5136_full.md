# ChatGPT Share: Архитектура стриминга ASR

Source: https://chatgpt.com/share/69f5014c-bfd4-8386-b892-8c7d889e5136
Exported: 2026-05-01

This file is an archived copy of the shared discussion used to design the live ASR mode.

## 1. You said

Я сделал сервис для распознавания речи https://github.com/yrsolo/asr-service
хочу его применять для переговором по зуму в прямом эфире.

сервис работает, но качество так себе поулчается. я посылаю раз в секунду туда записанный звук и он возвращает расшифровку. но получается рубленно. часть слов теряется или неверно понмиается, хотя модель как-то хорошая.

мне кажется даже тупо телефоне аудиоввод лучше работает, хотя там явно модель тупее.
сервис работает на 1080ти.


я так понимаю делао в какой-то умной постобработке, наложении чанков и всем таком.
надо разобраться как не колхозить велосипед а использовать профессиональный подход.

какая для такой задачи грамотная архитектура. хочется иметь маленькую задержку (в районе 1 сек) но качественный транскрипт. я понимаю что хвост в реальном времени может получаться не самого лучшего качества, но пусть. главное что бы потом доуточнялся

## 2. ChatGPT said

Разберу это как инженерную задачу стримингового ASR: где именно ломается качество, какие паттерны используют готовые системы, и как это можно приземлить на твой сервис с 1080 Ti без лишнего “велосипеда”.

Да, проблема почти наверняка не в “плохой модели”, а в **неправильной стриминговой обвязке**.

Сейчас ты делаешь примерно так:

```text
каждую секунду:  взять 1 секунду аудио  отправить в ASR  получить текст  показать текст
```

Для Whisper/faster-whisper это почти худший режим. Whisper не является нативно streaming-ASR моделью: ему нужен контекст до и после слова. Если резать звук по 1 секунде, ты постоянно режешь фразы, окончания слов, интонационные хвосты и паузы. В итоге модель угадывает куски без нормального контекста, а потом следующий кусок уже распознаёт без знания предыдущего.

В твоём репозитории уже заложена правильная идея: сервис заявлен как ASR-сервис с HTTP/WebSocket, pseudo-streaming, final/unstable transcript segmentation, а в roadmap прямо есть VAD tuning, better pseudo-streaming, stable/unstable tail revisions и overlap matching. То есть архитектурно ты уже идёшь в нужную сторону, просто теперь надо заменить “1 секунда = один независимый транскрипт” на полноценный стриминговый буфер. GitHub+1

## Как делают грамотно

Профессиональный подход для Whisper-подобной модели обычно такой:

```text
Zoom audio  ↓audio capture: маленькие PCM-фреймы 20–100 мс  ↓WebSocket stream на ASR-сервер  ↓ring buffer аудио, например последние 15–30 секунд  ↓VAD / endpointing  ↓каждые 500–1000 мс запускается распознавание НЕ последней 1 секунды,а окна 5–10 секунд с overlap  ↓новая гипотеза сравнивается с предыдущей  ↓совпавшая часть становится stable/final  ↓хвост остаётся unstable и может переписываться
```

Ключевой паттерн называется **local agreement**. Его использует Whisper-Streaming: система повторно распознаёт перекрывающиеся куски аудио и подтверждает только тот текст, который стабильно совпадает между последовательными гипотезами. В статье про Whisper-Streaming заявлена задержка около 3.3 секунды на длинной речи, но это именно компромисс качества и real-time, а не “честная 1 секунда до финального текста”. arXiv+1

## Почему телефон кажется лучше

Телефонный ввод обычно работает не как “одна секунда аудио → текст”. Там есть:

```text
акустический стримVADendpointingчастичные гипотезыстабилизация словязыковая модель / punctuationпереоценка хвоста
```

То есть он может быстро показать сырой хвост, но внутренне продолжает его уточнять. Именно это тебе и нужно повторить.

## Главная архитектурная идея

Нужно разделить текст на два слоя:

```text
JSON{  "stable": "Итак, по первому вопросу мы договорились, что",  "unstable": "следующий релиз переносим на..."}
```

`stable` — это уже подтверждённый текст. Его почти нельзя менять.

`unstable` — текущий хвост. Он может моргать, переписываться, исчезать, уточняться.

Для UI это выглядит нормально: пользователь видит почти живой текст, но понимает, что последние слова ещё “дышат”.

## Рекомендуемый pipeline для твоего сервиса

### 1. Не отправлять wav-файл раз в секунду

Лучше WebSocket с бинарными PCM-фреймами.

Например:

```text
client → server:  16 kHz mono PCM int16  frame_duration = 20/40/100 ms
```

На сервере держишь session state:

```text
PythonSessionState:    audio_ring_buffer    last_decode_time    committed_text    previous_hypothesis    unstable_text    vad_state    speaker_state optional
```

HTTP `/v1/transcribe/chunk` можно оставить для тестов, но для Zoom live основной путь должен быть `WS /v1/stream`. У тебя этот endpoint уже обозначен в README. GitHub

### 2. Распознавать не 1 секунду, а скользящее окно

Начальные параметры я бы взял такие:

```text
decode_interval: 0.7–1.0 секwindow_size: 6–8 секleft_context: 4–6 секright_unstable_tail: 1–2 секoverlap: почти весь window, потому что окно скользящее
```

То есть каждую секунду ты распознаёшь последние 6–8 секунд аудио, а не только последнюю секунду.

Пример:

```text
t=8s  → decode audio[0..8]t=9s  → decode audio[1..9]t=10s → decode audio[2..10]
```

Потом сравниваешь гипотезы. То, что повторилось в двух-трёх соседних декодах, коммитишь.

Именно короткие chunks без контекста считаются проблемными: в обзорах адаптации Whisper к real-time прямо отмечается, что слишком короткие фрагменты дают плохое качество, особенно когда слова или предложения режутся в начале/конце чанка. arXiv

### 3. Добавить local agreement

Упрощённая версия:

```text
Pythonprev = "мы можем перенести встречу на пятницу"curr = "мы можем перенести встречу на пятницу после обеда"common_prefix = "мы можем перенести встречу на пятницу"commit(common_prefix)unstable = "после обеда"
```

Но на практике надо сравнивать не просто строки, а токены/слова с нормализацией:

```text
- lowercase- убрать пунктуацию- ё/е нормализация- убрать лишние пробелы- fuzzy match для последних N слов
```

Лучше коммитить не весь common prefix, а только то, что находится **не у самого края текущего окна**. Последние 1–2 секунды всегда подозрительны.

### 4. Не давать Whisper резать речь как попало

Нужен VAD. Он решает две задачи:

```text
1. не гонять модель по тишине;2. финализировать фразу, когда человек реально замолчал.
```

Например:

```text
speech_start_threshold = 0.5speech_end_silence = 600–900 мсmin_speech_duration = 300 мс
```

Если была пауза 700–1000 мс, можно сделать forced finalization: распознать последний сегмент чуть более качественно и закоммитить.

Свежая работа WhisperPipe тоже описывает связку VAD + dynamic buffering + overlapping context windows как способ избежать потерь на границах сегментов. arXiv

### 5. Делать два режима распознавания

Я бы сделал так:

```text
fast pass:  каждые 0.7–1.0 сек  окно 6–8 сек  beam_size 1–3  выдаёт unstable/stablefinal pass:  при паузе, смене говорящего или конце фразы  сегмент целиком, например 8–20 сек  beam_size 5  temperature fallback можно включить  обновляет final-текст
```

То есть “живой хвост” быстрый, а финальный текст чуть позже доуточняется.

Это даст ощущение задержки около секунды, но качественный финальный транскрипт будет приходить с задержкой 2–4 секунды. Для переговоров это нормальный компромисс.

## Что конкретно не надо делать

Не надо:

```text
- распознавать независимые 1-секундные wav;- склеивать ответы простым append;- финализировать последние слова сразу;- делать LLM-постобработку вместо нормального ASR-буфера;- сначала чистить текст LLM-кой, а потом пытаться понять, что было stable.
```

LLM-постобработка нужна позже, отдельным слоем:

```text
ASR raw stable transcript  ↓punctuation / cleanup  ↓meeting notes / questions / action items
```

Но она не должна подменять ASR-стабилизацию.

## Практическая схема сообщений WebSocket

Я бы сделал такие события:

```text
JSON{  "type": "partial",  "session_id": "abc",  "stable_text": "Давайте тогда зафиксируем, что",  "unstable_text": "релиз переносим на следующую",  "audio_time_start": 12.4,  "audio_time_end": 19.8,  "revision": 41}
```

```text
JSON{  "type": "commit",  "session_id": "abc",  "text": "Давайте тогда зафиксируем, что релиз переносим на следующую неделю.",  "audio_time_start": 12.4,  "audio_time_end": 21.1,  "revision": 45}
```

```text
JSON{  "type": "final_segment",  "session_id": "abc",  "segment_id": "seg_0007",  "text": "Давайте тогда зафиксируем, что релиз переносим на следующую неделю.",  "audio_time_start": 12.4,  "audio_time_end": 21.1}
```

В UI:

```text
обычный текст = stable/finalсерый/курсив = unstable
```

## Минимальный алгоритм для первой нормальной версии

Прямо MVP:

```text
Pythonevery 1 second:    audio = ring_buffer.last(8 seconds)    result = whisper.transcribe(        audio,        language="ru",          # если в основном русский        task="transcribe",        beam_size=3,        vad_filter=False        # VAD лучше контролировать снаружи    )    hypothesis = normalize(result.text)    agreed = longest_common_prefix_words(        previous_hypothesis,        hypothesis    )    agreed = remove_last_n_words(agreed, 2)  # не коммитить самый край    new_commit = agreed - already_committed    emit_commit(new_commit)    emit_partial(hypothesis - committed)    previous_hypothesis = hypothesis
```

Потом улучшить:

```text
- fuzzy alignment вместо простого prefix;- word timestamps;- VAD;- final pass по endpointed-фразам;- speaker diarization отдельно.
```

## Что с задержкой в 1 секунду

Надо разделить понятия:

```text
1 секунда — можно показывать partial unstable;2–4 секунды — реалистичная задержка для stable/final на Whisper-like модели;5+ секунд — если нужен очень чистый текст и пунктуация.
```

Если требовать именно “финальный качественный текст через 1 секунду”, Whisper/faster-whisper — не идеальный класс моделей. Нужна нативная streaming-ASR модель. Например, NVIDIA в 2026 описывает Nemotron-ASR-Streaming как модель с поддержкой малых chunk sizes 80/160/560/1120 мс, но она английская, а тебе, судя по задаче, вероятно нужен русский/мультиязычный режим. Hugging Face

Поэтому для твоего случая разумнее не менять всё сразу, а сделать **Whisper-Streaming-like архитектуру** поверх faster-whisper.

## Что бы я поручил агенту

Вот хорошее ТЗ для агента:

```text
Цель:Переделать live ASR с независимых 1-секундных chunk transcription на stateful pseudo-streaming pipeline в стиле Whisper-Streaming.Нужно реализовать:1. Session-based WebSocket streaming.   - Клиент отправляет PCM mono 16 kHz int16 фреймами.   - Сервер хранит ring buffer аудио на 30 секунд.   - У каждой WS-сессии свой state.2. Sliding-window decoder.   - Каждые 700–1000 мс запускать faster-whisper на последних 6–8 секундах аудио.   - Параметры вынести в config:     stream_decode_interval_ms     stream_window_sec     stream_commit_margin_sec     stream_min_agreement_words     stream_model_profile3. Stable/unstable transcript.   - Не append-ить каждый результат.   - Сравнивать текущую и предыдущую гипотезы.   - Реализовать Local Agreement:     confirmed prefix → stable/commit     changing suffix → unstable   - Последние 1–2 секунды аудио не коммитить без паузы/VAD.4. VAD.   - Добавить Silero VAD или WebRTC VAD.   - VAD не должен сразу резать аудио для Whisper, он должен помогать endpointing.   - При speech_end_silence 700–1000 мс запускать final pass по завершённому речевому сегменту.5. Final pass.   - Для завершённых сегментов запускать более качественный decode.   - Обновлять final_segment.   - Не ломать уже отправленные commit-события без явного revision event.6. API events:   - partial   - commit   - final_segment   - session_stats   - error7. Метрики:   - decode_time_ms   - audio_window_sec   - real_time_factor   - committed_chars   - unstable_chars   - vad_state   - gpu_memory optional8. Тестовый стенд:   - Скрипт, который проигрывает заранее записанный wav как live stream.   - Сравнение режимов:     old 1s chunk append     sliding window without agreement     sliding window + local agreement     sliding window + VAD + final pass
```

## Самый важный вывод

Тебе не нужна “умная постобработка” в смысле LLM-магии. Тебе нужна **нормальная streaming ASR state machine**:

```text
audio ring buffer+ overlapping sliding windows+ local agreement+ stable/unstable text+ VAD endpointing+ final pass
```

И только после этого уже LLM-слой для красивых заголовков, вопросов, решений и задач.

Я бы первым делом сделал именно `sliding window + local agreement`. Даже без VAD это должно резко улучшить “рубленость” и потерю слов.

## 3. You said

мне бы хотелось бы всё же получать что-то с минимальной задержкой.
то есть например три вида пакетов.
например так
качественный - с 3-4х секундной задержкой.
рабочий - частично обработанное.
сырой - совсем грубые самые свежие символы.
а клиент уже по мере поступления заменяет спорные пакеты на хорошие.
такой компромис между скоростью и качеством.

все параметры задаём с клиента при создании сокета (или как там оно верно называется)

оцени архитектуру, предложи улучшения

## 4. ChatGPT said

Да, это хорошая идея: фактически ты описываешь multi-latency / multi-quality stream, где клиент видит быстрый черновик, но сервер постепенно “повышает класс достоверности” тех же участков аудио. Это ближе к тому, как ощущаются нормальные диктовки и live captions.

Архитектура с тремя видами пакетов — **правильная**. Я бы только чуть переименовал и формализовал её не как “три независимых текста”, а как **один изменяемый transcript timeline**, где разные события обновляют участки этого timeline с разным уровнем уверенности.

То есть не так:

```text
сырой текст отдельнорабочий текст отдельнокачественный текст отдельно
```

А так:

```text
есть аудио-временная шкала:[12.0s ─────────────── 18.5s]и по ней приходят версии:raw       → быстро, грубоdraft     → лучше, после локального согласованияfinal     → качественно, после VAD/end-of-phrase/final pass
```

## Как я бы назвал уровни

Твои названия понятны, но в API лучше использовать такие:

```text
raw       — самый свежий хвост, минимальная задержкаpartial   — рабочая гипотеза, уже с контекстомstable    — почти подтверждённый текстfinal     — финальная версия сегмента
```

Или если хочешь ровно три уровня:

```text
raw       — 200–500 мс задержкаdraft     — 1–2 сек задержкаfinal     — 3–5 сек задержка
```

Я бы всё-таки оставил **4 уровня**, потому что `stable` и `final` — разные вещи.

`stable` — это текст, который уже почти не будет меняться, потому что несколько декодов подряд согласились.

`final` — это текст, который привязан к завершённому речевому сегменту после паузы/VAD и качественного повторного прохода.

## Главное улучшение: пакеты должны быть не append, а revision

Клиент не должен просто дописывать новые строки. Он должен получать команды вида:

```text
создать/заменить участок transcript от t_start до t_end
```

Иначе ты быстро упрёшься в ад склеек.

Хорошая модель:

```text
JSON{  "type": "transcript.patch",  "segment_id": "seg_00042",  "revision": 7,  "quality": "raw",  "stability": 0.25,  "audio_start": 104.20,  "audio_end": 106.80,  "text": "ну тогда может быть пере..."}
```

Потом приходит лучше:

```text
JSON{  "type": "transcript.patch",  "segment_id": "seg_00042",  "revision": 8,  "quality": "draft",  "stability": 0.63,  "audio_start": 104.20,  "audio_end": 108.10,  "text": "ну тогда может быть перенесём это на пятницу"}
```

Потом финал:

```text
JSON{  "type": "transcript.patch",  "segment_id": "seg_00042",  "revision": 9,  "quality": "final",  "stability": 1.0,  "audio_start": 104.20,  "audio_end": 108.35,  "text": "Ну тогда, может быть, перенесём это на пятницу.",  "words": [    {"text": "Ну", "start": 104.20, "end": 104.36},    {"text": "тогда", "start": 104.38, "end": 104.71}  ]}
```

Клиент смотрит:

```text
segment_id тот жеrevision большеquality выше→ заменить старую версию новой
```

Это гораздо надёжнее, чем “удалить последние N символов и дописать”.

## Как должны работать три потока качества

Я бы сделал так.

### 1. Raw stream

Цель — показать хоть что-то почти сразу.

```text
задержка: 300–1000 мскачество: низкоеизменяемость: высокаяокно: последние 1.5–3 сек аудиочастота: 300–700 мс
```

Но важный момент: **raw лучше не пытаться делать полноценным Whisper-декодом каждую треть секунды**, особенно на 1080 Ti. Это может убить GPU и ухудшить общую задержку.

Варианты:

```text
вариант А:  raw = быстрый decode маленькой/квантованной модельювариант Б:  raw = тот же faster-whisper, но маленькое окно, beam_size=1вариант В:  raw = вообще опциональный, включается только если клиент запросил ultra-low-latency
```

Raw должен быть визуально “серым”, нестабильным. Его нельзя считать настоящим транскриптом.

### 2. Draft / working stream

Это основной live transcript.

```text
задержка: 1–2 секкачество: среднее/хорошееокно: 5–8 секчастота: 700–1000 мсмеханизм: sliding window + overlap + local agreement
```

Именно он должен быть главным для пользователя.

Он берёт последние 6–8 секунд аудио, распознаёт с контекстом, сравнивает с предыдущей гипотезой и коммитит то, что стабильно совпадает.

### 3. Final stream

Это качественный проход.

```text
задержка: 3–5 секкачество: максимальноетриггер: пауза, VAD endpoint, смена говорящего, конец репликиокно: целый речевой сегмент 5–30 секчастота: не постоянно, а по событиям
```

Тут можно включить:

```text
beam_size побольшеword timestampspunctuationнормализациювозможно, LLM-постобработку отдельным слоем
```

Но лучше не смешивать финальный ASR и красивую LLM-редактуру в одном событии. Сначала `final_asr`, потом отдельный `formatted`.

## Правильная схема на сервере

Я бы строил так:

```text
client audio stream  ↓session manager  ↓audio ring buffer 30–60 сек  ↓VAD / speech activity state  ↓scheduler  ├─ raw decoder       частый, дешёвый  ├─ draft decoder     основной sliding-window  └─ final decoder     по завершённым сегментам  ↓hypothesis aligner / revision manager  ↓WebSocket events to client
```

Ключевой компонент здесь — **revision manager**.

Он решает:

```text
- какой участок аудио сейчас обновляется;- какая версия новее;- какой quality выше;- можно ли заменить текст;- можно ли уже запретить дальнейшие изменения;- не пришёл ли старый результат позже нового.
```

Без этого при параллельных декодах начнётся хаос: raw может прийти позже draft, draft позже final и случайно перетереть хороший текст плохим.

## Очень важное правило

Пакеты должны иметь не только `quality`, но и **монотонный revision**.

Например:

```text
JSON{  "segment_id": "seg_00042",  "revision": 11,  "quality": "draft"}
```

Клиент принимает patch только если:

```text
новый revision > текущего revision для этого segment_id
```

Но есть нюанс: `raw revision 12` не должен перетирать `final revision 9`.

Поэтому лучше сравнивать так:

```text
final > stable > draft > raw
```

И отдельно `revision`.

Правило клиента:

```text
1. Если новый quality выше текущего — принять.2. Если quality тот же и revision выше — принять.3. Если quality ниже текущего — не перетирать, максимум показать отдельно как live_tail.
```

## Я бы разделил timeline на два слоя

Это важное улучшение.

### Основной transcript

Туда попадает только:

```text
draftstablefinal
```

### Live tail

Туда попадает:

```text
raw
```

То есть raw не должен постоянно переписывать основной текст. Он должен жить как “хвостик после курсора”.

В UI:

```text
[Финальный/стабильный текст обычным цветом] [draft чуть светлее] [raw серым]
```

Например:

```text
Итак, мы договорились перенести релиз на пятницу, а следующий вопрос —[raw: это по бюджету там надо бы...]
```

Потом raw исчезает и заменяется draft/final.

## Конфиг при создании сокета

Да, параметры лучше передавать при открытии сессии. Технически WebSocket нельзя красиво открыть с большим JSON body как обычный POST, поэтому есть два нормальных варианта.

### Вариант 1 — сначала HTTP create session

```text
httpPOST /v1/asr/sessions
```

```text
JSON{  "language": "ru",  "mode": "live_meeting",  "latency_profile": "balanced",  "audio": {    "sample_rate": 16000,    "channels": 1,    "format": "pcm_s16le"  },  "streams": {    "raw": true,    "draft": true,    "final": true  },  "raw": {    "enabled": true,    "interval_ms": 400,    "window_sec": 2.5  },  "draft": {    "interval_ms": 900,    "window_sec": 8,    "agreement_passes": 2,    "commit_margin_sec": 1.2  },  "final": {    "enabled": true,    "vad_silence_ms": 800,    "max_segment_sec": 25,    "beam_size": 5  }}
```

Ответ:

```text
JSON{  "session_id": "asr_123",  "ws_url": "ws://host/v1/asr/sessions/asr_123/stream"}
```

Потом клиент открывает WebSocket.

Это самый чистый вариант.

### Вариант 2 — config первым сообщением в WebSocket

Клиент открывает:

```text
WS /v1/asr/stream
```

Первое сообщение:

```text
JSON{  "type": "session.start",  "config": {    "language": "ru",    "latency_profile": "balanced"  }}
```

Сервер отвечает:

```text
JSON{  "type": "session.started",  "session_id": "asr_123",  "effective_config": {    "raw.interval_ms": 500,    "draft.window_sec": 8  }}
```

Это проще для MVP.

Я бы выбрал **второй вариант для MVP**, а первый — если сервис станет более промышленным.

## Нужно возвращать effective_config

Клиент может попросить невозможное:

```text
JSON{  "raw": {    "interval_ms": 100  },  "draft": {    "window_sec": 20  }}
```

А 1080 Ti не вывезет.

Поэтому сервер должен не молча страдать, а ответить:

```text
JSON{  "type": "session.started",  "requested_config": {...},  "effective_config": {    "raw": {      "interval_ms": 700,      "window_sec": 2.5    },    "draft": {      "interval_ms": 1000,      "window_sec": 7    }  },  "warnings": [    "raw.interval_ms increased from 100 to 700 due to gpu_profile=gtx1080ti"  ]}
```

Это очень важно. Иначе клиент задаст безумные параметры, а потом будет непонятно, почему всё лагает.

## Нужны latency profiles, а не только ручные параметры

Я бы дал клиенту простые пресеты:

```text
ultra_low_latencybalancedqualitygpu_safe
```

Например:

```text
JSON{  "latency_profile": "balanced",  "language": "ru",  "streams": ["raw", "draft", "final"]}
```

А ручные параметры — как override.

Пример:

```text
JSON{  "latency_profile": "balanced",  "draft": {    "window_sec": 10  }}
```

Так API будет удобнее и безопаснее.

## Пример профилей для 1080 Ti

Стартовые значения:

```text
ultra_low_latency:  raw:    interval_ms: 400    window_sec: 2.0    beam_size: 1  draft:    interval_ms: 800    window_sec: 5.0    beam_size: 1-2  final:    vad_silence_ms: 700    beam_size: 3balanced:  raw:    interval_ms: 600    window_sec: 2.5    beam_size: 1  draft:    interval_ms: 1000    window_sec: 7.0    beam_size: 2-3  final:    vad_silence_ms: 900    beam_size: 5quality:  raw:    enabled: false или interval_ms: 1000  draft:    interval_ms: 1200    window_sec: 10.0    beam_size: 3  final:    vad_silence_ms: 1000    beam_size: 5-8
```

Для переговоров я бы начал с `balanced`.

## Что делать с GPU

На 1080 Ti нельзя бесконтрольно запускать три параллельных декодера. Нужен **scheduler с приоритетами**.

Приоритеты такие:

```text
1. final — важнее всего, но не должен забивать live2. draft — основной пользовательский поток3. raw — можно дропать, если GPU занят
```

Но есть тонкость: если final будет занимать GPU слишком долго, live начнёт лагать. Поэтому я бы сделал так:

```text
draft имеет постоянный бюджетraw дропается первымfinal ставится в очередь и выполняется, когда есть окно
```

То есть raw — disposable. Его можно пропустить.

Правило:

```text
если raw decode не успел до следующего raw tick — пропускаем егоесли draft не успел — увеличиваем interval/effective degradationесли final очередь растёт — уменьшаем beam_size или режем max_segment_sec
```

## Сервер должен слать stats

Иначе ты не поймёшь, что происходит.

Например раз в секунду:

```text
JSON{  "type": "session.stats",  "audio_received_sec": 185.2,  "server_lag_ms": 720,  "raw_lag_ms": 480,  "draft_lag_ms": 1350,  "final_lag_ms": 4100,  "gpu_queue_size": 2,  "rtf": 0.42,  "dropped_raw_jobs": 17}
```

Это потом очень поможет в отладке.

## Как клиент должен заменять пакеты

Клиент хранит примерно такую структуру:

```text
TypeScripttype Segment = {  id: string  audioStart: number  audioEnd: number  text: string  quality: "raw" | "draft" | "stable" | "final"  revision: number  stability: number}
```

Приходит patch:

```text
TypeScriptfunction applyPatch(patch) {  const current = segments[patch.segment_id]  if (!current) {    segments[patch.segment_id] = patch    return  }  if (qualityRank(patch.quality) > qualityRank(current.quality)) {    segments[patch.segment_id] = patch    return  }  if (    patch.quality === current.quality &&    patch.revision > current.revision  ) {    segments[patch.segment_id] = patch    return  }  // не даём raw/draft перетереть final}
```

Но raw я бы держал отдельно:

```text
TypeScriptmainSegments: draft/stable/finalliveTail: raw
```

## Что делать с segment_id

Есть два варианта.

### Вариант простой

Сегменты создаются по VAD:

```text
speech start → новый segment_idspeech end → final pass
```

Проблема: пока VAD не понял границы, raw/draft могут относиться к “текущему открытому сегменту”.

### Вариант лучше

Есть `utterance_id` и `patch_id`.

```text
JSON{  "utterance_id": "utt_00042",  "patch_id": "utt_00042:rev_0007"}
```

Пока человек говорит, `utterance_id` один и тот же. Когда VAD нашёл паузу — utterance закрывается.

Для MVP достаточно `segment_id`.

## Ещё одно улучшение: token/word-level stability

Кроме `quality`, можно отдавать стабильность по словам:

```text
JSON{  "type": "transcript.patch",  "quality": "draft",  "text": "давайте перенесём релиз на следующую неделю",  "words": [    {"text": "давайте", "stability": 0.95},    {"text": "перенесём", "stability": 0.92},    {"text": "релиз", "stability": 0.88},    {"text": "на", "stability": 0.70},    {"text": "следующую", "stability": 0.55},    {"text": "неделю", "stability": 0.40}  ]}
```

Клиент может рисовать последние слова серее. Но это можно отложить.

## LLM-постобработка отдельно

Для переговоров тебе потом захочется:

```text
- знаки препинания;- абзацы;- кто что сказал;- вопросы;- решения;- action items;- краткое резюме.
```

Но это должен быть **ещё один слой**, не смешанный с ASR.

Например:

```text
ASR final segments  ↓formatter stream  ↓meeting notes stream
```

События:

```text
JSON{  "type": "formatted.patch",  "source_segment_ids": ["seg_00042", "seg_00043"],  "text": "Обсуждали перенос релиза на пятницу..."}
```

Иначе будет сложно понять, где реальная расшифровка, а где LLM уже литературно переписала речь.

## Я бы сделал такую финальную схему API

### Client → Server

Первое сообщение:

```text
JSON{  "type": "session.start",  "config": {    "language": "ru",    "audio": {      "format": "pcm_s16le",      "sample_rate": 16000,      "channels": 1    },    "latency_profile": "balanced",    "streams": {      "raw": true,      "draft": true,      "stable": true,      "final": true    },    "raw": {      "interval_ms": 500,      "window_sec": 2.5    },    "draft": {      "interval_ms": 900,      "window_sec": 8,      "agreement_passes": 2,      "commit_margin_sec": 1.2    },    "final": {      "vad_silence_ms": 850,      "max_segment_sec": 25,      "beam_size": 5    }  }}
```

Аудио:

```text
binary PCM frames
```

Или если всё JSON:

```text
JSON{  "type": "audio.chunk",  "seq": 152,  "timestamp_ms": 3040,  "audio_base64": "..."}
```

Но лучше binary, base64 не нужен.

### Server → Client

```text
JSON{  "type": "session.started",  "session_id": "asr_123",  "effective_config": {}}
```

```text
JSON{  "type": "transcript.patch",  "segment_id": "seg_00042",  "revision": 3,  "quality": "raw",  "stability": 0.2,  "audio_start": 104.2,  "audio_end": 106.1,  "text": "ну тогда может"}
```

```text
JSON{  "type": "transcript.patch",  "segment_id": "seg_00042",  "revision": 6,  "quality": "draft",  "stability": 0.65,  "audio_start": 104.2,  "audio_end": 108.0,  "text": "Ну тогда, может быть, перенесём это на пятницу"}
```

```text
JSON{  "type": "transcript.patch",  "segment_id": "seg_00042",  "revision": 9,  "quality": "final",  "stability": 1.0,  "audio_start": 104.2,  "audio_end": 108.4,  "text": "Ну тогда, может быть, перенесём это на пятницу."}
```

```text
JSON{  "type": "session.stats",  "server_lag_ms": 780,  "draft_lag_ms": 1450,  "final_lag_ms": 3900,  "gpu_queue_size": 1,  "dropped_raw_jobs": 5}
```

## Оценка твоей идеи

Я бы оценил так:

```text
Идея: 9/10
```

Она правильная и практически полезная.

Главные риски:

```text
1. Raw может съесть GPU и ухудшить draft/final.2. Без revision manager клиент начнёт получать хаотичные замены.3. Без audio_start/audio_end будет невозможно корректно заменять текст.4. Без effective_config клиент сможет запросить режим, который железо не тянет.5. Без отдельного liveTail raw будет портить основной transcript.
```

## Что бы я улучшил в твоей формулировке

Твоя идея:

```text
качественный — с 3–4 секундной задержкойрабочий — частично обработанноесырой — совсем грубые самые свежие символыклиент заменяет спорные пакеты на хорошие
```

Я бы оформил так:

```text
Система должна отдавать поток transcript patches с разным quality level.Уровни:- raw: минимальная задержка, может часто изменяться, не попадает в финальный transcript напрямую.- draft: основной live-текст, строится по sliding-window ASR с overlap.- stable: подтверждённая часть draft после local agreement.- final: результат качественного decode завершённого речевого сегмента.Клиент хранит transcript timeline и применяет patches по segment_id/revision/audio range.Пакеты более высокого качества заменяют пакеты более низкого качества.Пакеты более низкого качества не могут перетирать final/stable участки.
```

Вот это уже почти промышленная архитектура.

## 5. You said

отдельную модель для сверх-сырых не нужно.
задержка в 1 сек мне норм.
как сырое мы будем называть то что распозналось в последнюю секунду, то есть где нет перекрытия с прошлыми вариантами то есть самое сомнительное качетсво

## 6. ChatGPT said

Да, тогда архитектура становится проще и правильнее.

**Отдельный raw-декодер не нужен.**

`raw` — это не отдельный быстрый режим модели, а просто **самая правая, ещё не подтверждённая часть результата текущего sliding-window decode**.

То есть один основной ASR-проход раз в ~1 секунду:

```text
каждую 1 секунду:
  берём последние 6–10 секунд аудио
  распознаём всё окно
  сравниваем с предыдущими гипотезами
  левую совпавшую часть → stable/draft
  правый новый хвост → raw
```

## Тогда уровни лучше определить так

```text
final
  завершённый и перепроверенный сегмент после паузы/VAD/final pass

stable
  текст, который совпал в нескольких соседних распознаваниях

draft
  текст из текущего окна, который уже имеет контекст, но ещё не финализирован

raw
  самый свежий правый хвост текущей гипотезы,
  который ещё не имел шанса подтвердиться следующим окном
```

В твоей формулировке:

```text
raw = то, что распозналось в последнюю секунду
и ещё не перекрылось с прошлыми вариантами
```

Да, именно так.

## Как это выглядит во времени

Допустим, decode идёт раз в секунду, окно 8 секунд.

```text
t=10s: ASR audio[2..10]
  "давайте тогда перенесём встречу"

t=11s: ASR audio[3..11]
  "давайте тогда перенесём встречу на пятницу"

t=12s: ASR audio[4..12]
  "тогда перенесём встречу на пятницу после обеда"
```

Система видит, что кусок:

```text
"перенесём встречу на пятницу"
```

уже повторился/подтвердился, а:

```text
"после обеда"
```

ещё свежий. Значит:

```text
stable: "перенесём встречу на пятницу"
raw:    "после обеда"
```

## Важное уточнение

`raw` лучше определять не строго “последняя 1 секунда аудио”, а как:

```text
часть текущей гипотезы, которая:
- появилась только в последнем decode;
- не была подтверждена предыдущими decode;
- находится близко к правому краю аудио-окна.
```

Потому что слово может начаться 1.3 секунды назад, а закончиться сейчас. Если жёстко резать “последнюю секунду”, можно снова получить рубленость.

Лучше параметризовать так:

```text
JSON
{
  "raw_tail_sec": 1.5,
  "decode_interval_ms": 1000
}
```

То есть raw — это примерно последние 1–2 секунды гипотезы, но не по тупой аудио-границе, а по alignment/word timestamps, если они есть.

## Тогда pipeline такой

```text
audio stream
  ↓
ring buffer 30–60 sec
  ↓
каждую 1 sec: decode последних 8 sec
  ↓
hypothesis alignment
  ↓
разделение результата:
    final  — закрытые VAD-сегменты после качественного прохода
    stable — подтверждённое несколькими окнами
    draft  — текущая рабочая гипотеза
    raw    — неподтверждённый правый хвост
  ↓
transcript.patch events
```

## Конфиг сокета можно упростить

```text
JSON
{
  "type": "session.start",
  "config": {
    "language": "ru",
    "audio": {
      "format": "pcm_s16le",
      "sample_rate": 16000,
      "channels": 1
    },
    "decode": {
      "interval_ms": 1000,
      "window_sec": 8,
      "beam_size": 3
    },
    "agreement": {
      "stable_min_confirmations": 2,
      "raw_tail_sec": 1.5,
      "commit_margin_sec": 1.0
    },
    "final": {
      "enabled": true,
      "vad_silence_ms": 900,
      "beam_size": 5,
      "max_segment_sec": 25
    },
    "output": {
      "emit_raw": true,
      "emit_draft": true,
      "emit_stable": true,
      "emit_final": true
    }
  }
}
```

## Серверные события

Я бы оставил один тип события:

```text
JSON
{
  "type": "transcript.patch",
  "segment_id": "seg_00042",
  "revision": 12,
  "quality": "raw",
  "audio_start": 105.4,
  "audio_end": 106.8,
  "text": "после обеда",
  "stability": 0.2
}
```

Потом этот же участок может прийти как draft/stable/final:

```text
JSON
{
  "type": "transcript.patch",
  "segment_id": "seg_00042",
  "revision": 13,
  "quality": "stable",
  "audio_start": 105.4,
  "audio_end": 106.8,
  "text": "после обеда",
  "stability": 0.85
}
```

Но в клиенте я бы всё равно держал raw отдельно от основного transcript:

```text
main transcript: final + stable + draft
live tail: raw
```

Так интерфейс не будет дёргаться.

## Что важно для реализации

Самый важный компонент — **alignment между гипотезами**.

Нельзя просто брать “последние N символов”. Нужно сравнивать слова/токены:

```text
Python
prev = "давайте тогда перенесём встречу на пятницу"
curr = "давайте тогда перенесём встречу на пятницу после обеда"

confirmed = common_part(prev, curr)
new_tail = curr - confirmed
```

Но лучше не только `common prefix`, потому что начало окна будет сдвигаться, и первые слова могут исчезать:

```text
prev: "давайте тогда перенесём встречу на пятницу"
curr:          "тогда перенесём встречу на пятницу после обеда"
```

Тут нужен не prefix, а **fuzzy overlap alignment**:

```text
общий устойчивый кусок:
"тогда перенесём встречу на пятницу"

новый хвост:
"после обеда"
```

Для MVP можно сделать через `difflib.SequenceMatcher` по словам. Потом заменить на нормальный word-level aligner.

## Обновлённая оценка архитектуры

Теперь она выглядит ещё лучше:

```text
одна модель
один основной sliding-window decode
несколько уровней качества как результат анализа гипотез
финальный проход только по завершённым сегментам
```

Это экономнее для 1080 Ti и проще отлаживать.

Я бы зафиксировал так:

```text
raw — неподтверждённый хвост текущего decode
draft — текущая полная гипотеза активного сегмента
stable — часть draft, подтверждённая local agreement
final — результат финального decode по закрытому VAD-сегменту
```

И в ТЗ агенту прямо написать:

```text
Не реализовывать отдельную модель или отдельный raw-decoder.
Raw формируется из правого края основной sliding-window гипотезы.
Raw — это volatile live tail, который клиент обязан считать заменяемым.
```

Вот это уже хорошая, реалистичная и не слишком сложная архитектура.
