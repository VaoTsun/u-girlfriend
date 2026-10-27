CREATE SCHEMA IF NOT EXISTS dev;
COMMENT ON SCHEMA dev IS 'Пользовательская схема проекта u-barn: телеметрия, настройки, утилитарные данные';

CREATE TABLE IF NOT EXISTS dev.upsd_events (
  id bigserial PRIMARY KEY,
  host text,
  model text,
  started_at timestamp without time zone,
  ended_at timestamp without time zone,
  type text CHECK (type IN ('on_batt','alarm','low_batt','other')),
  batt_start integer,
  batt_min integer,
  batt_end integer,
  load_max integer,
  in_min numeric(6,1),
  in_max numeric(6,1),
  out_min numeric(6,1),
  out_max numeric(6,1),
  duration_sec integer,
  details jsonb DEFAULT '{}'::jsonb
);
COMMENT ON TABLE dev.upsd_events IS 'Событийный лог ИБП: окна работы от батареи (OB), тревоги (ALARM), низкий заряд (LB). Вместо 10-секундных замеров хранит факт отключения/тревоги с ключевыми параметрами.';
COMMENT ON COLUMN dev.upsd_events.host IS 'Хост/источник сбора (из dev.upsd.host)';
COMMENT ON COLUMN dev.upsd_events.model IS 'Модель ИБП (из dev.upsd.model)';
COMMENT ON COLUMN dev.upsd_events.started_at IS 'Время начала события';
COMMENT ON COLUMN dev.upsd_events.ended_at IS 'Время окончания события (NULL если не закрыто)';
COMMENT ON COLUMN dev.upsd_events.type IS 'Тип события: on_batt - работа от батареи, alarm - тревога, low_batt - низкий заряд, other - прочее';
COMMENT ON COLUMN dev.upsd_events.batt_start IS 'Заряд батареи (%) в начале события';
COMMENT ON COLUMN dev.upsd_events.batt_min IS 'Минимальный заряд батареи (%) за событие';
COMMENT ON COLUMN dev.upsd_events.batt_end IS 'Заряд батареи (%) в конце события';
COMMENT ON COLUMN dev.upsd_events.load_max IS 'Максимальная нагрузка ИБП (%) за событие';
COMMENT ON COLUMN dev.upsd_events.in_min IS 'Минимальное входное напряжение (В) за событие';
COMMENT ON COLUMN dev.upsd_events.in_max IS 'Максимальное входное напряжение (В) за событие';
COMMENT ON COLUMN dev.upsd_events.out_min IS 'Минимальное выходное напряжение (В) за событие';
COMMENT ON COLUMN dev.upsd_events.out_max IS 'Максимальное выходное напряжение (В) за событие';
COMMENT ON COLUMN dev.upsd_events.duration_sec IS 'Длительность события в секундах';
COMMENT ON COLUMN dev.upsd_events.details IS 'Доп. инфо в JSON (например список статус-флагов, время работы от батареи и др.)';

CREATE TABLE IF NOT EXISTS dev.upsd_hourly (
  host text NOT NULL,
  model text NOT NULL,
  hour timestamp without time zone NOT NULL,
  batt_min integer,
  batt_max integer,
  batt_last integer,
  load_min integer,
  load_max integer,
  in_min numeric(6,1),
  in_max numeric(6,1),
  out_min numeric(6,1),
  out_max numeric(6,1),
  cnt integer,
  status_mode text,
  PRIMARY KEY (host, model, hour)
);
COMMENT ON TABLE dev.upsd_hourly IS 'Почасовые агрегаты dev.upsd для штатного режима (OL/OL CHRG). Хранит min/max/last по ключевым параметрам вместо 10-секундных замеров. Сжимает ~360x по сравнению с исходными данными.';
COMMENT ON COLUMN dev.upsd_hourly.host IS 'Хост/источник сбора';
COMMENT ON COLUMN dev.upsd_hourly.model IS 'Модель ИБП';
COMMENT ON COLUMN dev.upsd_hourly.hour IS 'Начало часа (date_trunc("hour", time))';
COMMENT ON COLUMN dev.upsd_hourly.batt_min IS 'Мин. заряд батареи (%) за час';
COMMENT ON COLUMN dev.upsd_hourly.batt_max IS 'Макс. заряд батареи (%) за час';
COMMENT ON COLUMN dev.upsd_hourly.batt_last IS 'Заряд батареи (%) в последней точке часа';
COMMENT ON COLUMN dev.upsd_hourly.load_min IS 'Мин. нагрузка (%) за час';
COMMENT ON COLUMN dev.upsd_hourly.load_max IS 'Макс. нагрузка (%) за час';
COMMENT ON COLUMN dev.upsd_hourly.in_min IS 'Мин. входное напряжение (В) за час';
COMMENT ON COLUMN dev.upsd_hourly.in_max IS 'Макс. входное напряжение (В) за час';
COMMENT ON COLUMN dev.upsd_hourly.out_min IS 'Мин. выходное напряжение (В) за час';
COMMENT ON COLUMN dev.upsd_hourly.out_max IS 'Макс. выходное напряжение (В) за час';
COMMENT ON COLUMN dev.upsd_hourly.cnt IS 'Количество исходных точек, свернутых в агрегат';
COMMENT ON COLUMN dev.upsd_hourly.status_mode IS 'Наиболее частый ups_status за час (мода)';
