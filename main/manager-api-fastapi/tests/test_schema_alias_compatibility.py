from __future__ import annotations

import warnings

from fastapi._compat import get_model_fields

from app.schemas.correctword import CorrectWordFileBody
from app.schemas.device import DeviceReportRequest, DeviceUpdateRequest
from app.schemas.model import ModelProviderBody


def test_fastapi_can_rebuild_all_alias_fields_without_ineffective_metadata_warnings() -> None:
    # FastAPI reconstructs each body model field through TypeAdapter on first
    # request.  Keep this explicit regression because an unconstrained future
    # Pydantic upgrade emitted warnings for every aliased field on that path.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for model in (DeviceUpdateRequest, ModelProviderBody, DeviceReportRequest, CorrectWordFileBody):
            assert get_model_fields(model)


def test_representative_java_aliases_bind_and_serialize_in_both_supported_input_forms() -> None:
    update = DeviceUpdateRequest.model_validate({"autoUpdate": 1})
    assert update.auto_update == 1
    assert update.model_dump(by_alias=True)["autoUpdate"] == 1

    provider = ModelProviderBody.model_validate({"modelType": "LLM", "providerCode": "mock"})
    assert (provider.model_type, provider.provider_code) == ("LLM", "mock")

    camel_report = DeviceReportRequest.model_validate({"flashSize": 8, "chipModelName": "esp32"})
    snake_report = DeviceReportRequest.model_validate({"flash_size": 8, "chip_model_name": "esp32"})
    assert camel_report.flash_size == snake_report.flash_size == 8
    assert camel_report.chip_model_name == snake_report.chip_model_name == "esp32"

    words = CorrectWordFileBody.model_validate({"fileName": "words.txt", "fileSize": 12})
    assert words.file_name == "words.txt"
    assert words.file_size == 12
