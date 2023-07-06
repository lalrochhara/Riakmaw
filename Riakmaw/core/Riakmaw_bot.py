"""Riakmaw base"""
# Copyright (C) 2020 - 2023  Famhawite Infosys Team, <https://github.com/lalrochhara.git>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import logging
from typing import Optional

import aiohttp
import pyrogram

from Riakmaw.util.config import Config

from .command_dispatcher import CommandDispatcher
from .database_provider import DatabaseProvider
from .event_dispatcher import EventDispatcher
from .plugin_extenter import PluginExtender
from .telegram_bot import TelegramBot


class Riakmaw(TelegramBot, DatabaseProvider, PluginExtender, CommandDispatcher, EventDispatcher):
    # Initialized during instantiation
    log: logging.Logger
    http: aiohttp.ClientSession
    client: pyrogram.client.Client
    config: Config
    loop: asyncio.AbstractEventLoop
    stopping: bool

    def __init__(self, config: Config):
        self.config = config
        self.log = logging.getLogger("bot")
        self.loop = asyncio.get_event_loop()
        self.stopping = False

        # Initialize mixins
        super().__init__()

        # Initialize aiohttp session last in case another mixin fails
        self.http = aiohttp.ClientSession()

    @classmethod
    async def init_and_run(
        cls, config: Config, *, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> "Riakmaw":
        Riakmaw = None

        if loop:
            asyncio.set_event_loop(loop)

        try:
            Riakmaw = cls(config)
            await Riakmaw.run()
            return Riakmaw
        finally:
            asyncio.get_event_loop().stop()

   async def stop(self: "Riakmaw") -> None:
    if not self.client.is_connected:
        return
    await self.dispatch_event("stop")

        self.log.info("Stopping")
        if self.loaded:
            await self.dispatch_event("stop")
            if self.client.is_connected:
                await self.client.stop()

        await self.http.close()
        await self.db.close()

        self.log.info("Running post-stop hooks")
        if self.loaded:
            await self.dispatch_event("stopped")
