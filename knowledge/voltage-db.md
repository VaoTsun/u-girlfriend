<!-- СГЕНЕРИРОВАНО: node tools/dbdoc.js (girlfriend). НЕ РЕДАКТИРОВАТЬ РУКАМИ. -->
# Структура базы данных

Источник правды — сама база PostgreSQL (`192.168.88.171:5432`, база `d`,
пользователь `app`). Перегенерация: `node tools/dbdoc.js` (из корня girlfriend).

Схемы: `ar`, `dev`, `public`.

## Схема `ar`

### `ar.fired_alert`

строк ~4

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `fti` | integer | нет |  |
| `ts` | timestamp with time zone | нет | clock_timestamp() |
| `condition` | text | нет |  |

### `ar.last_alert`

строк ~1

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `lsrc` | integer | нет |  |
| `ts` | timestamp with time zone | нет | clock_timestamp() |
| `condition` | text | нет |  |

### `ar.notifications`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `ts_start` | timestamp with time zone | да | now() |
| `ts_done` | timestamp with time zone | да |  |
| `nsrc` | integer | да |  |
| `reason` | text | да |  |

### `ar.silencio`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `ssrc` | integer | да |  |
| `tsq_start` | timestamp with time zone | да |  |
| `tsq_done` | timestamp with time zone | да |  |

### `ar.src`

строк ~24

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет |  |
| `src` | text | нет |  |
| `sname` | text | нет |  |
| `stype` | text | да |  |
| `details` | text | да |  |
| `defcol` | text | да |  |
| `dots` | jsonb | да |  |

### `ar.threshold`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `ti` | integer | нет | nextval('ar.threshold_ti_seq'::regclass) |
| `tsrc` | integer | нет |  |
| `threshold` | double precision | нет |  |
| `col` | text | нет |  |
| `comparison` | character(1) | нет |  |
| `prio` | integer | да |  |
| `lts` | timestamp with time zone | да | clock_timestamp() |

### `ar.vals`

строк ~11 005 865

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет |  |
| `ts` | timestamp with time zone | да | clock_timestamp() |
| `src` | integer | да |  |
| `val` | double precision | да |  |
| `power` | text | да |  |
| `powerts` | timestamp with time zone | да |  |
| `rsii` | integer | да |  |
| `rsiits` | timestamp with time zone | да |  |
| `epower` | double precision | да |  |
| `epowerts` | timestamp with time zone | да |  |
| `batt` | double precision | да |  |
| `battts` | timestamp with time zone | да |  |
| `hum` | double precision | да |  |
| `cels` | double precision | да |  |

### `ar.volts_act`

строк ~5

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет | nextval('ar.volts_act_i_seq'::regclass) |
| `ts` | timestamp with time zone | да | now() |
| `val` | double precision | да |  |
| `action` | text | да |  |

## Схема `dev`

### `dev.nasushchnoe`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет | nextval('dev.nasushchnoe_i_seq'::regclass) |
| `title` | text | нет |  |
| `notes` | text | да |  |
| `created_at` | timestamp with time zone | нет | now() |
| `done` | boolean | нет | false |
| `done_at` | timestamp with time zone | да |  |

### `dev.nasushchnoe_dep`

строк ~0 · Насущное: (task_i, dep_i) - task_i ждёт, пока не сделана dep_i; DAG

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `task_i` | integer | нет |  |
| `dep_i` | integer | нет |  |

### `dev.organizer`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет | nextval('dev.organizer_i_seq'::regclass) |
| `title` | text | нет |  |
| `last_done` | timestamp with time zone | да |  |
| `notes` | text | да |  |
| `cron` | text | да | '0 7 1-5 * *'::text |
| `complete_this_period` | boolean | да |  |

### `dev.organizer_done`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет | nextval('dev.organizer_done_i_seq'::regclass) |
| `organizer_i` | integer | нет |  |
| `done_at` | timestamp with time zone | нет | now() |
| `note` | text | да |  |

### `dev.solcast`

строк ~14 140

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | bigint | нет | nextval('dev.solcast_i_seq'::regclass) |
| `ts` | timestamp with time zone | нет |  |
| `kw` | double precision | да |  |
| `kw10` | double precision | да |  |
| `kw90` | double precision | да |  |
| `kind` | character(1) | нет |  |
| `loaded_at` | timestamp with time zone | нет | clock_timestamp() |

### `dev.things`

строк ~0

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | нет |  |
| `ttype` | text | да |  |
| `model` | text | да |  |
| `notes` | text | да |  |

### `dev.upsd`

строк ~1 377 663

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `time` | timestamp without time zone | да |  |
| `host` | text | да |  |
| `model` | text | да |  |
| `serial` | text | да |  |
| `status_OL` | text | да |  |
| `ups_name` | text | да |  |
| `battery_charge_percent` | bigint | да |  |
| `battery_mfr_date` | text | да |  |
| `battery_runtime_low` | bigint | да |  |
| `battery_voltage` | double precision | да |  |
| `firmware` | text | да |  |
| `input_transfer_high` | bigint | да |  |
| `input_transfer_low` | bigint | да |  |
| `input_voltage` | double precision | да |  |
| `load_percent` | bigint | да |  |
| `nominal_battery_voltage` | bigint | да |  |
| `nominal_input_voltage` | bigint | да |  |
| `nominal_power` | bigint | да |  |
| `output_voltage` | double precision | да |  |
| `status_flags` | numeric | да |  |
| `time_left_ns` | bigint | да |  |
| `ups_delay_shutdown` | bigint | да |  |
| `ups_delay_start` | bigint | да |  |
| `ups_status` | text | да |  |
| `status_OB` | text | да |  |
| `status_LB` | text | да |  |
| `status_RB` | text | да |  |

## Схема `public`

### `public.vals_202502`

строк ~1 415 811

| колонка | тип | null | по умолчанию |
|---|---|---|---|
| `i` | integer | да |  |
| `ts` | timestamp with time zone | да |  |
| `src` | integer | да |  |
| `val` | double precision | да |  |
| `power` | text | да |  |
| `powerts` | timestamp with time zone | да |  |
| `rsii` | integer | да |  |
| `rsiits` | timestamp with time zone | да |  |
| `epower` | double precision | да |  |
| `epowerts` | timestamp with time zone | да |  |
| `batt` | integer | да |  |
| `battts` | timestamp with time zone | да |  |
| `hum` | double precision | да |  |
| `cels` | double precision | да |  |

