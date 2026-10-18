/* tools/dbdoc.js — генератор knowledge/voltage-db.md из самой базы.
 *
 * Лежит в репозитории girlfriend (память ассистента), но читает базу через
 * db.js из соседнего репозитория voltage (там же node_modules и .env).
 *
 * Зачем: структура БД не должна описываться руками (протухает и врёт).
 * Источник правды — information_schema/pg_catalog, отсюда — в markdown.
 *
 * Запуск (из корня girlfriend):
 *   node tools/dbdoc.js          (перегенерить knowledge/voltage-db.md)
 *   node tools/dbdoc.js --check  (только показать, что изменилось)
 *
 * Путь к voltage: по умолчанию ../voltage (папка рядом с girlfriend),
 * переопределяется переменной окружения VOLTAGE_DIR.
 */
const fs = require('fs');
const path = require('path');

const VOLTAGE = process.env.VOLTAGE_DIR || path.join(__dirname, '..', '..', 'voltage');
const OUT = path.join(__dirname, '..', 'knowledge', 'voltage-db.md');

// dotenv и pg лежат в node_modules voltage — подключаем их напрямую,
// чтобы генератору не нужен свой package.json и чтобы .env подхватился
// независимо от текущей директории запуска.
require(path.join(VOLTAGE, 'node_modules', 'dotenv')).config({ path: path.join(VOLTAGE, '.env') });
const db = require(path.join(VOLTAGE, 'db.js'));

async function q(name, text, values) {
	await db.syncSimpleQuery({ name, text, values: values || [] });
	return db.result.rows;
}

function mdEscape(s) {
	return String(s == null ? '' : s).replace(/\|/g, '\\|');
}

(async function () {
	const schemas = await q('schemas', `
		select nspname as schema
		from pg_namespace
		where nspname not in ('pg_catalog', 'information_schema')
		  and nspname not like 'pg_toast%'
		  and nspname not like 'pg_temp%'
		order by nspname`);

	const tables = await q('tables', `
		select c.relnamespace::regnamespace::text as schema,
		       c.relname as table,
		       c.reltuples::bigint as approx_rows,
		       obj_description(c.oid) as comment
		from pg_class c
		join pg_namespace n on n.oid = c.relnamespace
		where c.relkind in ('r', 'p', 'v', 'm')
		  and n.nspname not in ('pg_catalog', 'information_schema')
		  and n.nspname not like 'pg_toast%'
		  and n.nspname not like 'pg_temp%'
		order by 1, 2`);

	const columns = await q('columns', `
		select table_schema as schema, table_name as table, column_name as column,
		       data_type, udt_name, is_nullable, column_default,
		       character_maximum_length
		from information_schema.columns
		where table_schema not in ('pg_catalog', 'information_schema')
		  and table_schema not like 'pg_toast%'
		  and table_schema not like 'pg_temp%'
		order by table_schema, table_name, ordinal_position`);

	const functions = await q('functions', `
		select n.nspname as schema, p.proname as name,
		       pg_get_function_arguments(p.oid) as args,
		       pg_get_function_result(p.oid) as result
		from pg_proc p
		join pg_namespace n on n.oid = p.pronamespace
		where n.nspname not in ('pg_catalog', 'information_schema')
		  and n.nspname not like 'pg_toast%'
		  and n.nspname not like 'pg_temp%'
		  and p.prokind = 'f'
		order by 1, 2`);

	const bySchema = {};
	tables.forEach(t => {
		(bySchema[t.schema] = bySchema[t.schema] || []).push(t);
	});

	const lines = [];
	lines.push('<!-- СГЕНЕРИРОВАНО: node tools/dbdoc.js (girlfriend). НЕ РЕДАКТИРОВАТЬ РУКАМИ. -->');
	lines.push('# Структура базы данных');
	lines.push('');
	lines.push('Источник правды — сама база PostgreSQL (`192.168.88.171:5432`, база `d`,');
	lines.push('пользователь `app`). Перегенерация: `node tools/dbdoc.js` (из корня girlfriend).');
	lines.push('');
	if (schemas.length) {
		lines.push('Схемы: ' + schemas.map(s => '`' + s.schema + '`').join(', ') + '.');
		lines.push('');
	}

	schemas.forEach(s => {
		const ts = bySchema[s.schema] || [];
		if (!ts.length) return;
		lines.push('## Схема `' + s.schema + '`');
		lines.push('');
		ts.forEach(t => {
			const cols = columns.filter(c => c.schema === t.schema && c.table === t.table);
			const fns = functions.filter(f => f.schema === t.schema && f.name === t.table);
			lines.push('### `' + t.schema + '.' + t.table + '`');
			lines.push('');
			lines.push('строк ~' + Math.max(0, Math.round(t.approx_rows)).toLocaleString('en-US').replace(/,/g, ' ') +
				(t.comment ? ' · ' + mdEscape(t.comment) : ''));
			lines.push('');
			if (cols.length) {
				lines.push('| колонка | тип | null | по умолчанию |');
				lines.push('|---|---|---|---|');
				cols.forEach(c => {
					const type = c.data_type === 'USER-DEFINED' ? c.udt_name : c.data_type +
						(c.character_maximum_length ? '(' + c.character_maximum_length + ')' : '');
					lines.push('| `' + mdEscape(c.column) + '` | ' + mdEscape(type) +
						' | ' + (c.is_nullable === 'YES' ? 'да' : 'нет') +
						' | ' + mdEscape(c.column_default) + ' |');
				});
				lines.push('');
			}
			if (fns.length) {
				lines.push('Функции: ' + fns.map(f => '`' + f.name + '(' + f.args + ') → ' + f.result + '`').join(', '));
				lines.push('');
			}
		});
	});

	const content = lines.join('\n') + '\n';

	if (process.argv.includes('--check')) {
		const old = fs.existsSync(OUT) ? fs.readFileSync(OUT, 'utf8') : '';
		console.log(old === content ? 'knowledge/voltage-db.md не изменился' : 'knowledge/voltage-db.md УСТАРЕЛ — перегенерируй без --check');
		process.exit(old === content ? 0 : 1);
	}

	fs.mkdirSync(path.dirname(OUT), { recursive: true });
	fs.writeFileSync(OUT, content, 'utf8');
	console.log('записан', OUT, '| схем:', schemas.length, '| таблиц:', tables.length,
		'| колонок:', columns.length, '| функций:', functions.length);
	process.exit(0);
})().catch(e => { console.error('FAIL:', e.message || e); process.exit(1); });
