"""Tests for phones/cleaners.py"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

from django.utils import timezone

from twilio.rest import Client

from model_bakery import baker
from typing import Any
import pytest

from phones.cleaners import Counts, RelayNumberSyncChecker
from phones.models import RealPhone, RelayNumber, TwilioMessagingService

from .models_tests import make_phone_test_user


@pytest.fixture(autouse=True)
def mock_twilio_settings(settings) -> None:
    """Override settings to test Twilio accounts"""
    settings.PHONES_ENABLED = True
    settings.TWILIO_ACCOUNT_SID = f"AC{uuid4().hex}"
    settings.TWILIO_AUTH_TOKEN = uuid4().hex
    settings.TWILIO_SMS_APPLICATION_SID = f"AP{uuid4().hex}"
    settings.TWILIO_MESSAGING_SERVICE_SID = f"MG{uuid4().hex}"
    settings.TWILIO_BRAND_REGISTRATION_SID = f"BN{uuid4().hex}"
    settings.TWILIO_MAIN_NUMBER = "+12005550000"
    settings.TWILIO_CHANNEL = "prod"
    settings.TWILIO_MAIN_NUMBER_CHANNEL = "prod-main"


@pytest.fixture
def setup_relay_number_test_data(
    mock_twilio_client: Client,
    db,
    request,
    settings,
) -> None:
    """Setup Relay Numbers and mock Twilio responses for testing."""

    # Load per-test configuration via marks
    config_mark = request.node.get_closest_marker("relay_test_config")
    config_kwargs = config_mark.kwargs if config_mark else {}
    config_defaults = {
        "add_CA_number_to_relay_service": False,
        "add_CA_number_to_twilio_service": False,
        "main_number_in_twilio": True,
        "main_number_in_twilio_service": True,
        "main_number_in_wrong_service": False,
        "remove_number_from_relay": False,
        "remove_number_from_relay_service": False,
        "remove_number_from_twilio": False,
        "remove_number_from_twilio_service": False,
        "remove_relay_service": False,
        "remove_twilio_service": False,
        "relay_number_in_main_service": False,
        "relay_number_in_other_service": False,
    }
    config = {
        key: config_kwargs.get(key, default) for key, default in config_defaults.items()
    }

    # Make all objects created in the past
    verification_base_date = timezone.now() - timedelta(days=60)

    # Create TwilioMessagingService objects and related Twilio mock objects
    twilio_services: dict[str, TwilioMessagingService] = {}
    mock_twilio_services: dict[str, Mock] = {}
    service_data: dict[str, dict[str, Any]] = {
        "number_service": {
            # My deployment's service for RelayNumbers
            "friendly_name": "My Firefox Relay 1",
            "channel": settings.TWILIO_CHANNEL,
        },
        "main_service": {
            # My deployment's service for the main number
            "friendly_name": "My Firefox Relay Main Service",
            "channel": settings.TWILIO_MAIN_NUMBER_CHANNEL,
        },
        "other_service": {
            # A different deployment's service
            "friendly_name": "Stage Testing 1",
            "channel": "unknown",
            "twilio_numbers": ["+14015550001"],
            "in_relay": not config["remove_relay_service"],
            "in_twilio": not config["remove_twilio_service"],
        },
    }
    for service_key, data in service_data.items():
        twilio_numbers = data.pop("twilio_numbers", [])
        in_relay = data.pop("in_relay", True)
        in_twilio = data.pop("in_twilio", True)
        service_id = f"MG{uuid4().hex}"

        if in_relay:
            twilio_services[service_key] = baker.make(
                TwilioMessagingService,
                service_id=service_id,
                friendly_name=data["friendly_name"],
                use_case="notifications",
                campaign_use_case="PROXY",
                campaign_status="VERIFIED",
                channel=data["channel"],
            )

        if in_twilio:
            mock_twilio_service = create_mock_service(
                service_id, data["friendly_name"], settings
            )
            for service_number in twilio_numbers:
                mock_twilio_service.phone_numbers.list.return_value.append(
                    create_mock_number(service_number, settings)
                )
            mock_twilio_services[service_key] = mock_twilio_service
    mock_twilio_client.messaging.v1.services.list.return_value = list(
        mock_twilio_services.values()
    )

    # Mock responses for main number in Twilio
    twilio_objects: list[Mock] = []
    if config["main_number_in_twilio"]:
        twilio_objects.append(create_mock_number(settings.TWILIO_MAIN_NUMBER, settings))
    if config["main_number_in_twilio"] and config["main_number_in_twilio_service"]:
        if config["main_number_in_wrong_service"]:
            service_key = "number_service"
        else:
            service_key = "main_service"
        mock_twilio_service = mock_twilio_services[service_key]
        mock_twilio_service.phone_numbers.list.return_value.append(
            create_mock_number(settings.TWILIO_MAIN_NUMBER, settings)
        )

    # Configure test Relay numbers
    if config["relay_number_in_main_service"]:
        test_service_key = "main_service"
    elif config["relay_number_in_other_service"]:
        test_service_key = "other_service"
    else:
        test_service_key = "number_service"
    number_data: dict[str, dict[str, Any]] = {
        "+13015550001": {},
        "+13015550002": {
            "texts_forwarded": 1,
            "in_relay": not config["remove_number_from_relay"],
        },
        "+13015550003": {
            "texts_blocked": 1,
            "in_twilio": not config["remove_number_from_twilio"],
            "in_twilio_service": not config["remove_number_from_twilio_service"],
            "in_relay_service": not config["remove_number_from_relay_service"],
        },
        "+13065550004": {
            "calls_forwarded": 1,
            "country_code": "CA",
            "in_relay_service": config["add_CA_number_to_relay_service"],
            "in_twilio_service": config["add_CA_number_to_twilio_service"],
        },
        "+13015550005": {
            "calls_blocked": 1,
            "service_key": test_service_key,
        },
        "+13015550006": {"texts_forwarded": 1, "calls_forwarded": 1},
        "+13015550007": {"enabled": False},
    }

    # Setup RelayNumber instances and mock responses
    for num, (relay_number, data) in enumerate(number_data.items()):
        # Create user
        user = make_phone_test_user()

        # Create real number for user
        real_number = relay_number.replace("+1301", "+1201").replace("+1306", "+1639")
        verification_date = verification_base_date + timedelta(seconds=60 * num)
        country_code = data.pop("country_code", "US")
        service_key = data.pop("service_key", "number_service")
        baker.make(
            RealPhone,
            user=user,
            number=real_number,
            verification_sent_date=verification_date,
            verified=True,
            country_code=country_code,
        )

        # Create RelayNumber, link to TwilioMessagingService
        in_relay = data.pop("in_relay", True)
        in_relay_service = data.pop("in_relay_service", True)
        in_twilio = data.pop("in_twilio", True)
        in_twilio_service = data.pop("in_twilio_service", True)
        if in_relay_service:
            dj_service = twilio_services.get(service_key, None)
        else:
            dj_service = None
        if in_relay:
            baker.make(
                RelayNumber, user=user, number=relay_number, service=dj_service, **data
            )

        # Mock Twilio responses for number
        twilio_number = create_mock_number(relay_number, settings)
        if in_twilio:
            twilio_objects.append(twilio_number)
        if in_twilio and in_twilio_service:
            tw_service = mock_twilio_services.get(service_key, None)
        else:
            tw_service = None
        if tw_service:
            tw_service.phone_numbers.list.return_value.append(twilio_number)

    mock_twilio_client.incoming_phone_numbers.list.return_value = twilio_objects


def create_mock_service(service_id: str, friendly_name: str, settings) -> Mock:
    """
    Create a mock Service instance.

    Omitted properties: area_code_geomatch, date_created, date_updated,
    fallback_method, fallback_to_long_code, fallback_url, inbound_method,
    inbound_request_url, links, mms_converter, scan_message_content,
    smart_encoding, sticky_sender, synchronous_validation, url, validity_period
    """
    service = Mock(
        account_sid=settings.TWILIO_ACCOUNT_SID,
        sid=service_id,
        friendly_name=friendly_name,
        status_callback=f"{settings.SITE_ORIGIN}/api/v1/sms_status",
        us_app_to_person_registered=True,
        usecase="notifications",
        use_inbound_webhook_on_number=True,
    )
    service.phone_numbers.list.return_value = []
    service.us_app_to_person.list.return_value = [
        create_mock_us_app_to_person(service_id, settings)
    ]
    return service


def create_mock_us_app_to_person(messaging_service_sid, settings) -> Mock:
    """
    Create a mock US App to Person (brand registration) instance

    Omitted properties: brand_registration_sid, campaign_id, date_created,
    date_updated, description, has_embedded_links, has_embedded_phone,
    help_keywords, help_message, is_externally_registered, message_flow,
    message_samples, mock, opt_in_keywords, opt_in_message, opt_out_keywords,
    opt_out_message, rate_limits, url
    """
    return Mock(
        account_sid=settings.TWILIO_ACCOUNT_SID,
        brand_registration_sid=settings.TWILIO_BRAND_REGISTRATION_SID,
        messaging_service_sid=messaging_service_sid,
        sid=f"QE{uuid4().hex}",
        campaign_status="VERIFIED",
        us_app_to_person_usecase="PROXY",
    )


def create_mock_number(phone_number: str, settings) -> Mock:
    """
    Create a mock IncomingPhoneNumberInstance.

    Omitted properties: address_requirements, address_sid, api_version, beta,
    bundle_sid, capabilities, date_created, date_updated,
    emergency_address_sid, emergency_address_status, emergency_status,
    friendly_name, origin, sms_fallback_method, sms_fallback_url, sms_method,
    sms_url, status, status_callback, status_callback_method, trunk_sid, uri,
    voice_caller_id_lookup, voice_fallback_method, voice_fallback_url,
    voice_method,voice_receive_mode, voice_url
    """
    return Mock(
        account_sid=settings.TWILIO_ACCOUNT_SID,
        phone_number=phone_number,
        sid=f"PN{uuid4().hex}",
        sms_application_sid=settings.TWILIO_SMS_APPLICATION_SID,
        voice_application_sid=settings.TWILIO_SMS_APPLICATION_SID,
    )


def get_empty_counts() -> Counts:
    """Return the counts when Relay and Twilio are empty."""
    return {
        "summary": {"ok": 0, "needs_cleaning": 1},
        "relay_numbers": {
            "all": 0,
            "disabled": 0,
            "enabled": 0,
            "used": 0,
            "used_both": 0,
            "used_texts": 0,
            "used_calls": 0,
        },
        "twilio_numbers": {
            "all": 0,
            "in_both_db": 0,
            "only_relay_db": 0,
            "only_twilio_db": 0,
            "main_number": 0,
        },
        "twilio_messaging_services": {
            "all": 0,
            "in_both_db": 0,
            "only_relay_db": 0,
            "only_twilio_db": 0,
        },
    }


@pytest.mark.django_db
def test_relay_number_sync_checker_no_data() -> None:
    """RelayNumberSyncChecker works on an empty database."""
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    assert checker.counts == get_empty_counts()
    assert checker.clean() == 0
    report = checker.markdown_report()
    expected = """\
**Relay Numbers**:
- All: 0

**Twilio Numbers**:
- All: 0

**Twilio Messaging Services**:
- All: 0"""
    assert report == expected


@pytest.mark.django_db
def test_relay_number_sync_checker_just_main(mock_twilio_client, settings) -> None:
    """RelayNumberSyncChecker notes when just the main number is in Twilio."""
    mock_twilio_client.incoming_phone_numbers.list.return_value = [
        create_mock_number(settings.TWILIO_MAIN_NUMBER, settings)
    ]
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_empty_counts()
    expected_counts["twilio_numbers"]["all"] = 1
    expected_counts["twilio_numbers"]["main_number"] = 1
    expected_counts["twilio_numbers"]["main_number_in_service"] = 0
    expected_counts["twilio_numbers"]["main_number_no_service"] = 1
    expected_counts["twilio_numbers"]["main_number_wrong_service"] = 0
    assert checker.counts == expected_counts
    assert checker.clean() == 0


def get_synced_counts() -> Counts:
    """Return the counts when Relay is synced with Twilio"""
    return {
        "summary": {"ok": 11, "needs_cleaning": 0},
        "relay_numbers": {
            "all": 7,
            "disabled": 1,
            "enabled": 6,
            "used": 5,
            "used_calls": 2,
            "used_texts": 2,
            "used_both": 1,
        },
        "twilio_numbers": {
            "all": 8,
            "in_both_db": 7,
            "only_relay_db": 0,
            "only_twilio_db": 0,
            "cc_CA": 1,
            "cc_CA_in_service": 0,
            "cc_CA_no_service": 1,
            "cc_CA_only_relay_service": 0,
            "cc_CA_only_twilio_service": 0,
            "cc_US": 6,
            "cc_US_in_service": 6,
            "cc_US_correct_service": 6,
            "cc_US_wrong_service": 0,
            "cc_US_no_service": 0,
            "cc_US_only_relay_service": 0,
            "cc_US_only_twilio_service": 0,
            "main_number": 1,
            "main_number_in_service": 1,
            "main_number_no_service": 0,
            "main_number_wrong_service": 0,
        },
        "twilio_messaging_services": {
            "all": 3,
            "in_both_db": 3,
            "only_relay_db": 0,
            "only_twilio_db": 0,
            "synced_with_good_data": 3,
            "synced_but_bad_data": 0,
            "out_of_sync": 0,
            "ready": 3,
            "spam": 0,
            "full": 0,
        },
    }


def test_relay_number_sync_checker_synced_with_twilio(
    setup_relay_number_test_data,
) -> None:
    """RelayNumberSyncChecker detects that all phone numbers are synced."""
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 0
    assert checker.counts == get_synced_counts()
    assert checker.clean() == 0
    report = checker.markdown_report()
    expected = """\
**Relay Numbers**:
- All: 7
  - Enabled: 6 (85.7%)
    - Used: 5 (83.3%)
      - Used for Texts Only: 2 (40.0%)
      - Used for Calls Only: 2 (40.0%)
      - Used for Both      : 1 (20.0%)

**Twilio Numbers**:
- All: 8
  - In Both Databases      : 7 (87.5%)
    - Country Code CA: 1 (14.3%)
      - In a Messaging Service          : 0 (  0.0%)
      - Only in Relay Messaging Service : 0 (  0.0%)
      - Only in Twilio Messaging Service: 0 (  0.0%)
      - Not in a Messaging Service (OK) : 1 (100.0%)
    - Country Code US: 6 (85.7%)
      - In a Messaging Service          : 6 (100.0%)
        - In Correct Service: 6 (100.0%)
        - In Wrong Service  : 0 (  0.0%)
      - Only in Relay Messaging Service : 0 (  0.0%)
      - Only in Twilio Messaging Service: 0 (  0.0%)
      - Not in a Messaging Service      : 0 (  0.0%)
  - Main Number in Twilio  : 1 (12.5%)
    - In Correct Messaging Service: 1 (100.0%)
    - In Wrong Messaging Service  : 0 (  0.0%)
    - Not in a Messaging Service  : 0 (  0.0%)
  - Only in Relay Database : 0 ( 0.0%)
  - Only in Twilio Database: 0 ( 0.0%)

**Twilio Messaging Services**:
- All: 3
  - In Both Databases      : 3 (100.0%)
    - In Sync, Good Data: 3 (100.0%)
      - Ready to Use  : 3 (100.0%)
      - Marked as Spam: 0 (  0.0%)
      - Full          : 0 (  0.0%)
    - In Sync, Bad Data : 0 (  0.0%)
    - Out of Sync       : 0 (  0.0%)
  - Only in Relay Database : 0 (  0.0%)
  - Only in Twilio Database: 0 (  0.0%)"""
    assert report == expected


@pytest.mark.relay_test_config(main_number_in_twilio=False)
def test_relay_number_sync_checker_main_not_in_twilio(
    setup_relay_number_test_data,
) -> None:
    """RelayNumberSyncChecker detects when the main number is not in Twilio."""
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["all"] -= 1
    expected_counts["twilio_numbers"]["main_number"] = 0
    del expected_counts["twilio_numbers"]["main_number_in_service"]
    del expected_counts["twilio_numbers"]["main_number_no_service"]
    del expected_counts["twilio_numbers"]["main_number_wrong_service"]
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(remove_number_from_twilio=True)
def test_relay_number_sync_checker_relay_number_not_in_twilio(
    setup_relay_number_test_data,
) -> None:
    """RelayNumberSyncChecker detects when a RelayNumber is not in Twilio."""
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["cc_US_in_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_only_relay_service"] += 1
    expected_counts["twilio_numbers"]["in_both_db"] -= 1
    expected_counts["twilio_numbers"]["only_relay_db"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(remove_number_from_relay=True)
def test_relay_number_sync_checker_twilio_number_not_in_relay(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a Twilio Number is not a RelayNumber.

    It is OK to have more numbers in Twilio. This can happen when multiple
    deployments use the same Twilio Account.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 0
    expected_counts = get_synced_counts()
    expected_counts["summary"]["ok"] -= 1
    expected_counts["relay_numbers"]["all"] -= 1
    expected_counts["relay_numbers"]["enabled"] -= 1
    expected_counts["relay_numbers"]["used"] -= 1
    expected_counts["relay_numbers"]["used_texts"] -= 1
    expected_counts["twilio_numbers"]["cc_US"] -= 1
    expected_counts["twilio_numbers"]["cc_US_in_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["in_both_db"] -= 1
    expected_counts["twilio_numbers"]["only_twilio_db"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(remove_number_from_relay_service=True)
def test_relay_number_sync_checker_relay_number_not_in_relay_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a number is in a Twilio Messaging
    Service but not the Relay TwilioMessagingService table.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["cc_US_in_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_only_twilio_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(remove_number_from_twilio_service=True)
def test_relay_number_sync_checker_relay_number_not_in_twilio_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a number is in a Twilio Messaging
    Service but not the Relay TwilioMessagingService table.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["cc_US_in_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_only_relay_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(
    remove_number_from_relay_service=True, remove_number_from_twilio_service=True
)
def test_relay_number_sync_checker_relay_number_not_in_service(
    setup_relay_number_test_data,
) -> None:
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["cc_US_in_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_no_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(
    add_CA_number_to_twilio_service=True, add_CA_number_to_relay_service=True
)
def test_relay_number_sync_checker_canada_number_in_service(
    setup_relay_number_test_data,
) -> None:
    """
    Checker detects when a Canadian number is assigned to a service.

    Canadian numbers do not need to be assigned to a Messaging Service,
    but it is not an issue if they are.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 0
    expected_counts = get_synced_counts()
    expected_counts["twilio_numbers"]["cc_CA_in_service"] += 1
    expected_counts["twilio_numbers"]["cc_CA_correct_service"] = 1
    expected_counts["twilio_numbers"]["cc_CA_wrong_service"] = 0
    expected_counts["twilio_numbers"]["cc_CA_no_service"] -= 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(add_CA_number_to_relay_service=True)
def test_relay_number_sync_checker_canada_number_in_relay_service_only(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a Canadian number is assigned to only
    a Relay TwilioMessagingService instance.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["ok"] -= 1
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["twilio_numbers"]["cc_CA_only_relay_service"] += 1
    expected_counts["twilio_numbers"]["cc_CA_no_service"] -= 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(add_CA_number_to_twilio_service=True)
def test_relay_number_sync_checker_canada_number_in_twilio_service_only(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a Canadian number is assigned to only
    a Twilio Messaging Service.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["ok"] -= 1
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["twilio_numbers"]["cc_CA_only_twilio_service"] += 1
    expected_counts["twilio_numbers"]["cc_CA_no_service"] -= 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(main_number_in_wrong_service=True)
def test_relay_number_sync_checker_main_number_in_wrong_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when the main number is not assigned to a
    Twilio Messaging Service.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["main_number_in_service"] -= 1
    expected_counts["twilio_numbers"]["main_number_wrong_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(relay_number_in_main_service=True)
def test_relay_number_sync_checker_relay_number_in_wrong_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when the main number is not assigned to a
    Twilio Messaging Service.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_wrong_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(relay_number_in_other_service=True)
def test_relay_number_sync_checker_relay_number_in_other_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when the main number is not assigned to a
    Twilio Messaging Service.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["cc_US_correct_service"] -= 1
    expected_counts["twilio_numbers"]["cc_US_wrong_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(main_number_in_twilio_service=False)
def test_relay_number_sync_checker_main_number_not_in_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when the main number is not assigned to a
    Twilio Messaging Service.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_numbers"]["main_number_in_service"] -= 1
    expected_counts["twilio_numbers"]["main_number_no_service"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(remove_relay_service=True)
def test_relay_number_sync_checker_only_twilio_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a Twilio Messaging Service does not have
    a matching Relay TwilioMessagingService instance.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_messaging_services"]["in_both_db"] -= 1
    expected_counts["twilio_messaging_services"]["synced_with_good_data"] -= 1
    expected_counts["twilio_messaging_services"]["ready"] -= 1
    expected_counts["twilio_messaging_services"]["only_twilio_db"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0


@pytest.mark.relay_test_config(remove_twilio_service=True)
def test_relay_number_sync_checker_only_relay_service(
    setup_relay_number_test_data,
) -> None:
    """
    RelayNumberSyncChecker detects when a Relay TwilioMessagingService instance
    does not have a matching Twilio Messaging Service.
    """
    checker = RelayNumberSyncChecker()
    assert checker.issues() == 1
    expected_counts = get_synced_counts()
    expected_counts["summary"]["needs_cleaning"] += 1
    expected_counts["summary"]["ok"] -= 1
    expected_counts["twilio_messaging_services"]["in_both_db"] -= 1
    expected_counts["twilio_messaging_services"]["synced_with_good_data"] -= 1
    expected_counts["twilio_messaging_services"]["ready"] -= 1
    expected_counts["twilio_messaging_services"]["only_relay_db"] += 1
    assert checker.counts == expected_counts
    assert checker.clean() == 0
