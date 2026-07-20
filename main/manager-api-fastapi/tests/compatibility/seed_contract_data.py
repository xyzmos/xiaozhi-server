from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from typing import Any

import asyncmy  # type: ignore[import-untyped]
from asyncmy.cursors import DictCursor  # type: ignore[import-untyped]

ADMIN_ID = 9_007_199_254_740_993
NORMAL_ID = 9_007_199_254_740_994
EXPIRED_ID = 9_007_199_254_740_995
ADMIN_TOKEN = "contract-admin-token"  # noqa: S105 - isolated fixture credential
NORMAL_TOKEN = "contract-normal-token"  # noqa: S105 - isolated fixture credential
EXPIRED_TOKEN = "contract-expired-token"  # noqa: S105 - isolated fixture credential
SERVER_SECRET = "contract-server-secret"  # noqa: S105 - isolated fixture credential
MQTT_SIGNATURE_KEY = "contract-mqtt-signature-key"
MIGRATION_TIMESTAMP_TABLES = (
    "ai_model_provider",
    "sys_dict_data",
    "sys_dict_type",
)


def _database_config(port: int, database: str) -> dict[str, Any]:
    return {
        "host": "127.0.0.1",
        "port": port,
        "user": "xiaozhi_test",
        "password": "isolated-test-only",
        "db": database,
        "charset": "utf8mb4",
        "autocommit": False,
    }


async def _query_params(port: int, database: str, codes: tuple[str, ...]) -> dict[str, str | None]:
    connection = await asyncmy.connect(**_database_config(port, database))
    try:
        async with connection.cursor(DictCursor) as cursor:
            placeholders = ",".join(["%s"] * len(codes))
            await cursor.execute(
                f"SELECT param_code,param_value FROM sys_params WHERE param_code IN ({placeholders})",  # noqa: S608
                codes,
            )
            rows = await cursor.fetchall()
            return {str(row["param_code"]): row["param_value"] for row in rows}
    finally:
        connection.close()


async def _seed_database(
    port: int,
    database: str,
    crypto_params: dict[str, str | None],
    mock_port: int,
) -> None:
    connection = await asyncmy.connect(**_database_config(port, database))
    now = datetime(2026, 7, 20, 12, 34, 56)
    try:
        async with connection.cursor(DictCursor) as cursor:
            await cursor.execute(
                "SELECT id FROM ai_agent_correct_word_file WHERE file_name LIKE 'contract-run-%'"
            )
            generated_file_ids = [str(row["id"]) for row in await cursor.fetchall()]
            if generated_file_ids:
                placeholders = ",".join(["%s"] * len(generated_file_ids))
                await cursor.execute(
                    f"DELETE FROM ai_agent_correct_word_mapping WHERE file_id IN ({placeholders})",  # noqa: S608
                    generated_file_ids,
                )
                await cursor.execute(
                    f"DELETE FROM ai_agent_correct_word_item WHERE file_id IN ({placeholders})",  # noqa: S608
                    generated_file_ids,
                )
                await cursor.execute(
                    f"DELETE FROM ai_agent_correct_word_file WHERE id IN ({placeholders})",  # noqa: S608
                    generated_file_ids,
                )
            await cursor.execute("DELETE FROM ai_ota WHERE id='contract-ota-run'")

            for identifier, username, super_admin in (
                (ADMIN_ID, "contract-admin", 1),
                (NORMAL_ID, "contract-user", 0),
                (EXPIRED_ID, "contract-expired", 0),
            ):
                await cursor.execute(
                    "INSERT INTO sys_user(id,username,password,super_admin,status,create_date,updater,creator,"
                    "update_date) "
                    "VALUES(%s,%s,%s,%s,1,%s,%s,%s,%s) AS fixture ON DUPLICATE KEY UPDATE "
                    "username=fixture.username,password=fixture.password,super_admin=fixture.super_admin,status=1,"
                    "create_date=fixture.create_date,updater=fixture.updater,creator=fixture.creator,"
                    "update_date=fixture.update_date",
                    (
                        identifier,
                        username,
                        "$2a$10$contract.fixture.not.used",
                        super_admin,
                        now,
                        ADMIN_ID,
                        ADMIN_ID,
                        now,
                    ),
                )
            for identifier, user_id, token, expires in (
                (ADMIN_ID, ADMIN_ID, ADMIN_TOKEN, datetime(2099, 1, 1)),
                (NORMAL_ID, NORMAL_ID, NORMAL_TOKEN, datetime(2099, 1, 1)),
                (EXPIRED_ID, EXPIRED_ID, EXPIRED_TOKEN, datetime(2020, 1, 1)),
            ):
                await cursor.execute(
                    "INSERT INTO sys_user_token(id,user_id,token,expire_date,update_date,create_date) "
                    "VALUES(%s,%s,%s,%s,%s,%s) AS fixture ON DUPLICATE KEY UPDATE token=fixture.token,"
                    "expire_date=fixture.expire_date,update_date=fixture.update_date,create_date=fixture.create_date",
                    (identifier, user_id, token, expires, now, now),
                )

            parameter_values: dict[str, str | None] = {
                **crypto_params,
                "server.secret": SERVER_SECRET,
                "server.auth.enabled": "true",
                "server.websocket": "ws://127.0.0.1:18080/xiaozhi/v1/",
                "server.mqtt_gateway": "mqtt://127.0.0.1:1883",
                "server.mqtt_manager_api": f"127.0.0.1:{mock_port}",
                "server.mqtt_signature_key": MQTT_SIGNATURE_KEY,
                "server.ota": "http://127.0.0.1:18082/xiaozhi/ota/",
                "server.frontend.url": "http://127.0.0.1:8001",
            }
            for code, value in parameter_values.items():
                await cursor.execute(
                    "UPDATE sys_params SET param_value=%s,update_date=%s WHERE param_code=%s",
                    (value, now, code),
                )

            await cursor.execute(
                "INSERT INTO ai_agent(id,user_id,agent_code,agent_name,system_prompt,summary_memory,chat_history_conf,"
                "lang_code,language,sort,creator,created_at,updater,updated_at) "
                "VALUES(%s,%s,%s,%s,NULL,%s,1,%s,%s,7,%s,%s,%s,%s) AS fixture ON DUPLICATE KEY UPDATE "
                "user_id=fixture.user_id,agent_code=fixture.agent_code,agent_name=fixture.agent_name,"
                "system_prompt=NULL,summary_memory=fixture.summary_memory,chat_history_conf=1,"
                "lang_code=fixture.lang_code,language=fixture.language,sort=7,creator=fixture.creator,"
                "created_at=fixture.created_at,updater=fixture.updater,updated_at=fixture.updated_at",
                (
                    "contract-agent-1",
                    NORMAL_ID,
                    "contract-agent-code",
                    "Contract Agent",
                    "fixture memory",
                    "zh-CN",
                    "zh",
                    NORMAL_ID,
                    now,
                    NORMAL_ID,
                    now,
                ),
            )
            await cursor.execute(
                "INSERT INTO ai_device(id,user_id,mac_address,last_connected_at,auto_update,board,alias,agent_id,"
                "app_version,sort,creator,create_date,updater,update_date) "
                "VALUES(%s,%s,%s,%s,1,%s,NULL,%s,%s,3,%s,%s,%s,%s) "
                "AS fixture ON DUPLICATE KEY UPDATE user_id=fixture.user_id,mac_address=fixture.mac_address,"
                "last_connected_at=fixture.last_connected_at,auto_update=1,board=fixture.board,alias=NULL,"
                "agent_id=fixture.agent_id,app_version=fixture.app_version,sort=3,creator=fixture.creator,"
                "create_date=fixture.create_date,updater=fixture.updater,update_date=fixture.update_date",
                (
                    "contract-device-1",
                    NORMAL_ID,
                    "AA:BB:CC:DD:EE:01",
                    now,
                    "esp32s3",
                    "contract-agent-1",
                    "1.2.3",
                    NORMAL_ID,
                    now,
                    NORMAL_ID,
                    now,
                ),
            )
            await cursor.execute(
                "INSERT INTO ai_model_provider(id,model_type,provider_code,name,fields,sort,creator,create_date,"
                "updater,update_date) "
                "VALUES(%s,%s,%s,%s,CAST(%s AS JSON),9,%s,%s,%s,%s) AS fixture ON DUPLICATE KEY UPDATE "
                "model_type=fixture.model_type,provider_code=fixture.provider_code,name=fixture.name,"
                "fields=fixture.fields,sort=9,creator=fixture.creator,create_date=fixture.create_date,"
                "updater=fixture.updater,update_date=fixture.update_date",
                (
                    "contract-provider",
                    "LLM",
                    "contract",
                    "Contract Provider",
                    '[{"key":"api_key","label":"API Key","type":"string"}]',
                    ADMIN_ID,
                    now,
                    ADMIN_ID,
                    now,
                ),
            )
            await cursor.execute(
                "INSERT INTO ai_agent_correct_word_file(id,file_name,word_count,content,creator,created_at,updater,"
                "updated_at) "
                "VALUES(%s,%s,2,%s,%s,%s,%s,%s) AS fixture ON DUPLICATE KEY UPDATE "
                "file_name=fixture.file_name,word_count=2,content=fixture.content,creator=fixture.creator,"
                "created_at=fixture.created_at,updater=fixture.updater,updated_at=fixture.updated_at",
                (
                    "contract-words",
                    "合同词表.txt",
                    "小智,小志\nESP32,esp32",
                    NORMAL_ID,
                    now,
                    NORMAL_ID,
                    now,
                ),
            )
            await cursor.execute("DELETE FROM ai_agent_correct_word_item WHERE file_id=%s", ("contract-words",))
            for word_id, source, target in (
                ("contract-word-1", "小智", "小志"),
                ("contract-word-2", "ESP32", "esp32"),
            ):
                await cursor.execute(
                    "INSERT INTO ai_agent_correct_word_item(id,file_id,source_word,target_word) VALUES(%s,%s,%s,%s)",
                    (word_id, "contract-words", source, target),
                )
            await cursor.execute(
                "INSERT INTO ai_agent_correct_word_mapping(id,agent_id,file_id,creator,created_at,updater,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) AS fixture ON DUPLICATE KEY UPDATE creator=fixture.creator,"
                "created_at=fixture.created_at,updater=fixture.updater,updated_at=fixture.updated_at",
                ("contract-word-map", "contract-agent-1", "contract-words", NORMAL_ID, now, NORMAL_ID, now),
            )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


async def _sync_migration_timestamps(port: int) -> None:
    """Copy baseline-generated timestamps for rows shared by both schemas.

    Several Liquibase seed changesets use the database current timestamp.  The
    Java and FastAPI schemas are migrated a few seconds apart, which would make
    otherwise identical read responses differ.  The isolated contract fixture
    treats Java as the behavior baseline and aligns only the audit timestamps of
    matching migration rows; it does not copy business data or change IDs.
    """

    connection = await asyncmy.connect(**_database_config(port, "manager_fastapi_test"))
    try:
        async with connection.cursor(DictCursor) as cursor:
            for table in MIGRATION_TIMESTAMP_TABLES:
                await cursor.execute(
                    f"UPDATE manager_fastapi_test.`{table}` AS target "  # noqa: S608
                    f"JOIN manager_java_test.`{table}` AS baseline ON baseline.id=target.id "
                    "SET target.create_date=baseline.create_date,target.update_date=baseline.update_date"
                )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


async def seed(port: int, mock_port: int) -> None:
    crypto = await _query_params(
        port,
        "manager_java_test",
        ("server.public_key", "server.private_key"),
    )
    if not crypto.get("server.public_key") or not crypto.get("server.private_key"):
        raise RuntimeError("Java baseline must be started once before seeding so its SM2 keypair exists")
    for database in ("manager_java_test", "manager_fastapi_test"):
        await _seed_database(port, database, crypto, mock_port)
    await _sync_migration_timestamps(port)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql-port", type=int, default=13316)
    parser.add_argument("--mock-port", type=int, default=18084)
    args = parser.parse_args()
    asyncio.run(seed(args.mysql_port, args.mock_port))


if __name__ == "__main__":
    main()
