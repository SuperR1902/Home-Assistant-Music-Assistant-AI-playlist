"""Config flow for AI Mood Playlist."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AI_TASK_ENTITY,
    CONF_AUTO_DISCOVER_AFTER_REFRESH,
    CONF_MA_CONFIG_ENTRY,
    CONF_REFRESH_INTERVAL_HOURS,
    DEFAULT_AUTO_DISCOVER_AFTER_REFRESH,
    DEFAULT_REFRESH_INTERVAL_HOURS,
    DOMAIN,
)


def _music_assistant_entries(hass) -> list[dict[str, str]]:
    """Return configured Music Assistant config entries as label/value pairs."""
    entries = hass.config_entries.async_entries("music_assistant")
    return [{"label": e.title or e.entry_id, "value": e.entry_id} for e in entries]


class AiMoodPlaylistConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AI Mood Playlist."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        ma_entries = _music_assistant_entries(self.hass)
        if not ma_entries:
            # No point showing a form with an empty, unusable dropdown --
            # send the user to set up Music Assistant first.
            return self.async_abort(reason="no_music_assistant")

        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_MA_CONFIG_ENTRY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="AI Mood Playlist",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_MA_CONFIG_ENTRY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=e["value"], label=e["label"])
                            for e in ma_entries
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_AI_TASK_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="ai_task")
                ),
                vol.Optional(
                    CONF_REFRESH_INTERVAL_HOURS, default=DEFAULT_REFRESH_INTERVAL_HOURS
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=168, step=1, mode="box")
                ),
                vol.Optional(
                    CONF_AUTO_DISCOVER_AFTER_REFRESH,
                    default=DEFAULT_AUTO_DISCOVER_AFTER_REFRESH,
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return AiMoodPlaylistOptionsFlow()


class AiMoodPlaylistOptionsFlow(config_entries.OptionsFlowWithReload):
    """Allow changing settings after setup.

    Subclassing OptionsFlowWithReload (rather than plain OptionsFlow) means
    Home Assistant automatically reloads the config entry after options are
    saved -- no manual update-listener needed, and no custom __init__ that
    could collide with core's own handling of self.config_entry (assigning
    to that attribute directly is a hard error as of HA 2025.12).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(title="", data={})

        current_ai_task = self.config_entry.data.get(CONF_AI_TASK_ENTITY)
        current_interval = self.config_entry.data.get(
            CONF_REFRESH_INTERVAL_HOURS, DEFAULT_REFRESH_INTERVAL_HOURS
        )
        current_auto_discover = self.config_entry.data.get(
            CONF_AUTO_DISCOVER_AFTER_REFRESH, DEFAULT_AUTO_DISCOVER_AFTER_REFRESH
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AI_TASK_ENTITY, default=current_ai_task
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="ai_task")
                ),
                vol.Optional(
                    CONF_REFRESH_INTERVAL_HOURS, default=current_interval
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=168, step=1, mode="box")
                ),
                vol.Optional(
                    CONF_AUTO_DISCOVER_AFTER_REFRESH, default=current_auto_discover
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

