from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field

from app.schemas.common import JavaModel


class DeviceRegisterRequest(JavaModel):
    mac_address: str | None = None


class DeviceUnbindRequest(JavaModel):
    device_id: str | None = None


class DeviceUpdateRequest(JavaModel):
    auto_update: int | None = None
    alias: str | None = None


class DeviceManualAddRequest(JavaModel):
    agent_id: str | None = None
    board: str | None = None
    app_version: str | None = None
    mac_address: str | None = None


class DeviceToolCallRequest(JavaModel):
    name: str | None = None
    arguments: dict[str, Any] | None = None


class DeviceAddressBookAliasRequest(JavaModel):
    mac_address: str | None = None
    target_mac: str | None = None
    alias: str | None = None


class DeviceAddressBookPermissionRequest(JavaModel):
    mac_address: str | None = None
    target_mac: str | None = None
    has_permission: bool | None = None


class ChipInfo(JavaModel):
    model: int | None = None
    cores: int | None = None
    revision: int | None = None
    features: int | None = None


class ApplicationInfo(JavaModel):
    name: str | None = None
    version: str | None = None
    compile_time: str | None = Field(
        default=None,
        validation_alias=AliasChoices("compile_time", "compileTime"),
        serialization_alias="compile_time",
    )
    idf_version: str | None = Field(
        default=None,
        validation_alias=AliasChoices("idf_version", "idfVersion"),
        serialization_alias="idf_version",
    )
    elf_sha256: str | None = Field(
        default=None,
        validation_alias=AliasChoices("elf_sha256", "elfSha256"),
        serialization_alias="elf_sha256",
    )


class PartitionInfo(JavaModel):
    label: str | None = None
    type: int | None = None
    subtype: int | None = None
    address: int | None = None
    size: int | None = None


class OtaPartitionInfo(JavaModel):
    label: str | None = None


class BoardInfo(JavaModel):
    type: str | None = None
    ssid: str | None = None
    rssi: int | None = None
    channel: int | None = None
    ip: str | None = None
    mac: str | None = None


class DeviceReportRequest(JavaModel):
    version: int | None = None
    flash_size: int | None = Field(
        default=None,
        validation_alias=AliasChoices("flash_size", "flashSize"),
        serialization_alias="flash_size",
    )
    minimum_free_heap_size: int | None = Field(
        default=None,
        validation_alias=AliasChoices("minimum_free_heap_size", "minimumFreeHeapSize"),
        serialization_alias="minimum_free_heap_size",
    )
    mac_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mac_address", "macAddress"),
        serialization_alias="mac_address",
    )
    uuid: str | None = None
    chip_model_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("chip_model_name", "chipModelName"),
        serialization_alias="chip_model_name",
    )
    chip_info: ChipInfo | None = Field(
        default=None,
        validation_alias=AliasChoices("chip_info", "chipInfo"),
        serialization_alias="chip_info",
    )
    application: ApplicationInfo | None = None
    partition_table: list[PartitionInfo] | None = Field(
        default=None,
        validation_alias=AliasChoices("partition_table", "partitionTable"),
        serialization_alias="partition_table",
    )
    ota: OtaPartitionInfo | None = None
    board: BoardInfo | None = None


class OtaRecord(JavaModel):
    id: str | None = None
    firmware_name: str | None = None
    type: str | None = None
    version: str | None = None
    size: int | None = None
    remark: str | None = None
    firmware_path: str | None = None
    sort: int | None = None
    updater: int | None = None
    update_date: str | None = None
    creator: int | None = None
    create_date: str | None = None
