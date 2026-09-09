"""Shared DeviceInfo so all AI Mood Playlist entities group under one device page."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="AI Mood Playlist",
        manufacturer="Custom",
        model="AI Mood Playlist",
        entry_type=DeviceEntryType.SERVICE,
    )
