"""Riakmaw command dispatcher"""
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

import inspect
from typing import TYPE_CHECKING, Any, Iterable, MutableMapping, Optional, Union

from pyrogram import ContinuePropagation, errors
from pyrogram.client import Client
from pyrogram.enums.chat_action import ChatAction
from pyrogram.enums.chat_type import ChatType
from pyrogram.filters import Filter, create
from pyrogram.types import Message

from Riakmaw import command, plugin, util
from Riakmaw.error import CommandHandlerError, CommandInvokeError, ExistingCommandError
from Riakmaw.util.cache_limiter import CacheLimiter

from .Riakmaw_mixin_base import MixinBase

if TYPE_CHECKING:
    from .Riakmaw_bot import Riakmaw


class CommandDispatcher(MixinBase):
    # Initialized during instantiation
    commands: MutableMapping[str, command.Command]

    # Private
    __limiter: CacheLimiter

    def __init__(self: "Riakmaw", **kwargs: Any) -> None:
        # Initialize command map
        self.commands = {}

        self.__limiter = CacheLimiter(ttl=10, max_value=3)

        # Propagate initialization to other mixins
        super().__init__(**kwargs)

    def register_command(
        self: "Riakmaw",
        plug: plugin.Plugin,
        name: str,
        func: command.CommandFunc,
        *,
        filters: Optional[Union[util.types.CustomFilter, Filter]] = None,
        aliases: Iterable[str] = [],
    ) -> None:
        if getattr(func, "_listener_filters", None):
            self.log.warning(
                "@listener.filters decorator only for ListenerFunc. Filters will be ignored..."
            )

        if filters:
            self.log.debug("Registering filter '%s' into '%s'", type(filters).__name__, name)
            util.misc.check_filters(filters, self)

        cmd = command.Command(name, plug, func, filters, aliases)

        if name in self.commands:
            orig = self.commands[name]
            raise ExistingCommandError(orig, cmd)

        self.commands[name] = cmd

        for alias in cmd.aliases:
            if alias in self.commands:
                orig = self.commands[alias]
                raise ExistingCommandError(orig, cmd, alias=True)

            self.commands[alias] = cmd

    def unregister_command(self: "Riakmaw", cmd: command.Command) -> None:
        del self.commands[cmd.name]

        for alias in cmd.aliases:
            try:
                del self.commands[alias]
            except KeyError:
                continue

    def register_commands(self: "Riakmaw", plug: plugin.Plugin) -> None:
        for name, func in util.misc.find_prefixed_funcs(plug, "cmd_"):
            done = False

            try:
                self.register_command(
                    plug,
                    name,
                    func,
                    filters=getattr(func, "_cmd_filters", None),
                    aliases=getattr(func, "_cmd_aliases", []),
                )
                done = True
            finally:
                if not done:
                    self.unregister_commands(plug)

    def unregister_commands(self: "Riakmaw", plug: plugin.Plugin) -> None:
        # Can't unregister while iterating, so collect commands to unregister afterwards
        to_unreg = []

        for name, cmd in self.commands.items():
            # Let unregister_command deal with aliases
            if name != cmd.name:
                continue

            if cmd.plugin == plug:
                to_unreg.append(cmd)

        # Actually unregister the commands
        for cmd in to_unreg:
            self.unregister_command(cmd)

    def command_predicate(self: "Riakmaw") -> Filter:
        async def func(_: Filter, client: Client, message: Message) -> bool:
            if message.via_bot:
                return False

            if (message.chat and message.chat.type == ChatType.CHANNEL) or (
                message.sender_chat
                and message.forward_from_chat
                and message.forward_from_chat.id == message.sender_chat.id
            ):
                return False  # ignore channel broadcasts

            if message.text is not None and message.text.startswith("/"):
                user = message.from_user or message.sender_chat
                # check user limiter
                if await self.__limiter.exceeded(user.id):
                    return False

                try:
                    parts = message.text.split()
                    parts[0] = parts[0][1:]

                    # Check if bot command contains a valid username
                    # eg: /ping@dRiakmaw_bot will return True
                    # If current bot instance is dRiakmaw_bot else False
                    if self.user.username and self.user.username in parts[0]:
                        # Remove username from command
                        parts[0] = parts[0].replace(f"@{self.user.username}", "")

                    # Filter if command is not in commands
                    try:
                        cmd = self.commands[parts[0]]
                    except KeyError:
                        return False

                    # Check additional built-in filters
                    if cmd.filters:
                        if inspect.iscoroutinefunction(cmd.filters.__call__):
                            if not await cmd.filters(client, message):
                                return False
                        else:
                            if not await util.run_sync(cmd.filters, client, message):
                                return False

                    message.command = parts
                    return True
                finally:
                    # Increment user limit
                    await self.__limiter.increment(user.id)

            return False

        return create(func, "CustomCommandFilter")

    async def on_command(
        self: "Riakmaw", client: Client, message: Message  # skipcq: PYL-W0613
    ) -> None:
        # cmd never raises KeyError because we checked on command_predicate
        cmd = self.commands[message.command[0]]
        try:
            # Construct invocation context
            ctx = command.Context(
                self,
                message,
                1 + len(message.command[0]) + 1,
            )

            # Parse and convert handler required parameters
            signature = inspect.signature(cmd.func)
            args = []  # type: list[Any]
            kwargs = {}  # type: MutableMapping[str, Any]
            if len(signature.parameters) > 1:
                args, kwargs = await util.converter.parse_arguments(signature, ctx, cmd.func)

            # Invoke command function
            try:
                ret = await cmd.func(ctx, *args, **kwargs)

                # Response shortcut
                if ret is not None:
                    async with ctx.action(ChatAction.TYPING):
                        await ctx.respond(
                            ret,
                            disable_web_page_preview=True,
                        )
            except errors.MessageNotModified:
                cmd.plugin.log.warning(
                    "Command '%s' triggered a message edit with no changes; make sure there is only a single bot instance running",
                    cmd.name,
                )
            except Exception as e:  # skipcq: PYL-W0703
                constructor_invoke = CommandInvokeError(
                    f"raised from {type(e).__name__}: {str(e)}"
                ).with_traceback(e.__traceback__)
                chat = ctx.chat
                user = ctx.msg.from_user
                cmd.plugin.log.error(
                    "Error in command '%s'\n"
                    "  Data:\n"
                    "    • Chat    -> %s (%d)\n"
                    "    • Invoker -> %s (%d)\n"
                    "    • Input   -> %s\n",
                    cmd.name,
                    chat.title if chat else None,
                    chat.id if chat else -1,
                    user.first_name if user else None,
                    user.id if user else -1,
                    ctx.input,
                    exc_info=constructor_invoke,
                )
                await self.dispatch_alert(f"command `/{message.command[0]}`", constructor_invoke)

            await self.dispatch_event("command", ctx, cmd)
        except Exception as e:  # skipcq: PYL-W0703
            constructor_handler = CommandHandlerError(
                f"raised from {type(e).__name__}: {str(e)}"
            ).with_traceback(e.__traceback__)
            chat = message.chat
            user = message.from_user
            cmd.plugin.log.error(
                "Error in command handler\n"
                "  Data:\n"
                "    • Chat    -> %s (%d)\n"
                "    • Invoker -> %s (%d)\n"
                "    • Input   -> %s\n",
                cmd.name,
                chat.title if chat else None,
                chat.id if chat else None,
                user.first_name if user else None,
                user.id if user else None,
                message.command,
                exc_info=constructor_handler,
            )
            await self.dispatch_alert(
                f"command `/{message.command[0]}` handler", constructor_handler
            )
        finally:
            # Continue processing handler of on_message
            raise ContinuePropagation
