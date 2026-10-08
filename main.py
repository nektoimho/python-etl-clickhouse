import logging

from etl import extract, transform, connect, load, show_report


def main():
    # Вывод сообщений в терминал и файл etl.log.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler("etl.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    client = None

    try:
        # Читаем и очищаем данные.
        raw_rows = extract()
        cleaned_rows = transform(raw_rows)

        # Подключаемся и загружаем данные.
        client = connect()
        load(client, cleaned_rows)

        # Показываем аналитический отчёт.
        show_report(client)

        logging.info("ETL успешно завершён")

    except Exception:
        logging.exception("Ошибка выполнения ETL")
        raise

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()