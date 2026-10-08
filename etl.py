import csv
import json
import logging
import xml.etree.ElementTree as ET

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import clickhouse_connect


DATA_DIR = Path(__file__).resolve().parent / "data"

COLUMNS = [
    "id",
    "product",
    "quantity",
    "price",
    "sale_date",
    "source",
]


def extract():
    """Чтение данных из CSV, JSON и XML."""
    rows = []

    # Чтение CSV.
    with (DATA_DIR / "sales.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        for row in csv.DictReader(file):
            rows.append({**row, "source": "CSV"})

    # Чтение JSON.
    with (DATA_DIR / "sales.json").open(
        encoding="utf-8-sig"
    ) as file:
        json_rows = json.load(file)

    if not isinstance(json_rows, list):
        raise ValueError("В JSON должен находиться список объектов")

    for row in json_rows:
        if not isinstance(row, dict):
            raise ValueError("Запись JSON должна быть объектом")
        rows.append({**row, "source": "JSON"})

    # Чтение XML.
    root = ET.parse(DATA_DIR / "sales.xml").getroot()

    for element in root.findall("sale"):
        row = {
            child.tag: child.text or ""
            for child in element
        }
        rows.append({**row, "source": "XML"})

    logging.info("Прочитано записей: %s", len(rows))
    return rows


def parse_date(value):
    """Преобразование даты из одного из двух форматов."""
    text = str(value).strip()

    for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Некорректная дата: {text}")


def transform(rows):
    """Очистка данных, проверка значений и удаление повторов."""
    cleaned = []
    seen_ids = set()
    rejected = 0
    duplicates = 0

    for row in rows:
        try:
            sale_id = int(str(row["id"]).strip())
            quantity = int(str(row["quantity"]).strip())

            # Убираем лишние пробелы.
            product = " ".join(
                str(row.get("product") or "").split()
            )

            # Приводим цену к единому формату.
            price_text = (
                str(row["price"])
                .strip()
                .replace(" ", "")
                .replace(",", ".")
            )
            price = Decimal(price_text)

            if not 1 <= sale_id <= 4294967295:
                raise ValueError("ID вне диапазона UInt32")

            if not product:
                raise ValueError("Пустое название товара")

            if not 1 <= quantity <= 4294967295:
                raise ValueError(
                    "Количество должно быть положительным "
                    "и помещаться в UInt32"
                )

            if not price.is_finite() or price < 0:
                raise ValueError("Некорректная цена")

            rounded_price = price.quantize(Decimal("0.01"))

            if price != rounded_price:
                raise ValueError("Цена содержит доли меньше копейки")

            if rounded_price >= Decimal("10000000000"):
                raise ValueError("Цена слишком велика")

            sale_date = parse_date(row["sale_date"])

            if not 1970 <= sale_date.year <= 2148:
                raise ValueError("Дата вне учебного диапазона")

            # Проверяем повторы внутри файлов.
            if sale_id in seen_ids:
                duplicates += 1
                logging.warning("Повтор ID=%s пропущен", sale_id)
                continue

            seen_ids.add(sale_id)

            cleaned.append([
                sale_id,
                product,
                quantity,
                rounded_price,
                sale_date,
                row["source"],
            ])

        except (KeyError, ValueError, TypeError, InvalidOperation) as error:
            rejected += 1
            logging.warning(
                "Отклонена запись ID=%s: %s",
                row.get("id", "?"),
                error,
            )

    logging.info(
        "После очистки: %s; ошибок: %s; повторов: %s",
        len(cleaned),
        rejected,
        duplicates,
    )
    return cleaned


def connect():
    """Подключение к ClickHouse."""
    return clickhouse_connect.get_client(
        host="localhost",
        port=8123,
        username="etl_user",
        password="StudyPass123",
        database="analytics",
    )


def load(client, rows):
    """Создание таблицы и загрузка новых продаж."""
    client.command("""
        CREATE TABLE IF NOT EXISTS sales (
            id UInt32,
            product String,
            quantity UInt32,
            price Decimal(12, 2),
            sale_date Date,
            source LowCardinality(String)
        )
        ENGINE = MergeTree()
        ORDER BY (sale_date, id)
    """)

    # Для небольшого учебного проекта получаем все загруженные ID.
    existing_ids = {
        row[0]
        for row in client.query("SELECT id FROM sales").result_rows
    }

    new_rows = [
        row for row in rows
        if row[0] not in existing_ids
    ]

    if new_rows:
        client.insert(
            "sales",
            new_rows,
            column_names=COLUMNS,
        )

    logging.info("Загружено новых записей: %s", len(new_rows))


def show_report(client):
    """Расчёт количества проданных товаров и выручки."""
    result = client.query("""
        SELECT
            product,
            sum(quantity) AS units,
            sum(quantity * price) AS revenue
        FROM sales
        GROUP BY product
        ORDER BY revenue DESC
    """)

    print("\nАНАЛИТИЧЕСКИЙ ОТЧЁТ")

    for product, units, revenue in result.result_rows:
        print(
            f"{product}: {units} шт., "
            f"выручка {revenue:.2f} руб."
        )