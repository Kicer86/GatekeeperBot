
import asyncio
import discord
import logging

from dataclasses import dataclass
from discord.utils import escape_markdown
from typing import Dict, List, Tuple, Set


class RolesSource:
    def invalidate_cache(self):                                                             # clear cache
        pass

    def set_notifier(self, notifier):                                                       # set callback for notifying in the name of bot on dedicated channel
        pass

    def get_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:        # get roles for member. Returns (roles to be added, roles to be removed) which may be cached.
        pass

    def fetch_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:      # get roles for member. Returns (roles to be added, roles to be removed) omiting cache
        pass

    def get_user_auto_roles_reaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:      # get roles for member who reacted on a message in auto roles channel
        pass

    def get_user_auto_roles_unreaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:    # get roles for member who unreacted on a message in auto roles channel
        pass


@dataclass
class BotConfig:
    dedicated_channel: int
    roles_source: RolesSource
    auto_roles_channels: List[int]


class RolesBot(discord.Client):
    def __init__(self, config: BotConfig, logger):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents = intents)

        self.config = config
        self.channel = None
        self.logger = logger
        self.config.roles_source.set_notifier(self._write_to_dedicated_channel)


    async def on_ready(self):
        self.logger.info(f"Bot is ready as {self.user}")

        if len(self.guilds) != 1:
            raise RuntimeError(f"Invalid number of guilds: {len(self.guilds)}")

        guild = self.guilds[0]
        self.channel = await self.fetch_channel(self.config.dedicated_channel)

        self.logger.debug(f"Using channel {self.config.dedicated_channel} for notifications")

        for auto_roles_channel in self.config.auto_roles_channels:
            channel = await self.fetch_channel(auto_roles_channel)
            self.logger.debug(f"Auto roles: listening for reactions in channel {channel}")


    async def on_message(self, message):
        if self.user in message.mentions and len(message.mentions) == 1:
            if not any(role.name == "Administrator" for role in message.author.roles):
                await message.channel.send("Tylko administrator może wydawać polecenia.")
                return

            message_content = message.content.strip()
            bot_mention = f"<@{self.user.id}>"
            if message_content.startswith(bot_mention):
                command = message_content[len(bot_mention):].strip()
                if command == "refresh":
                    async with self.channel.typing():
                        await self._refresh_roles(message.guild.members)
                if command == "status":
                    async with self.channel.typing():
                        await self._write_to_dedicated_channel("Ujdzie")

    async def on_member_join(self, member):
        self.logger.info(f"Applying roles for new user: {member.name}.")
        roles_to_add, roles_to_remove = self.config.roles_source.fetch_user_roles(member)
        self.logger.debug(f"Roles to add: {roles_to_add}, roles to remove: {roles_to_remove}")

        added_roles, removed_roles = await self._update_member_roles(member, roles_to_add, roles_to_remove)

        await self._single_user_report(f"Aktualizacja ról nowego użytkownika {member.name} zakończona.", added_roles, removed_roles)


    async def on_raw_reaction_add(self, payload):
        await self._update_auto_roles(payload, self.config.roles_source.get_user_auto_roles_reaction)


    async def on_raw_reaction_remove(self, payload):
        await self._update_auto_roles(payload, self.config.roles_source.get_user_auto_roles_unreaction)


    async def _write_to_dedicated_channel(self, message: str):
        self.logger.debug(f"Sending message {repr(message)}")
        await self.channel.send(message)


    async def _single_user_report(self, title: str, added_roles: List[str], removed_roles: List[str]):
        self.logger.info("Print report")
        message_parts = []

        message_parts.append(title)
        if len(added_roles) > 0:
            added_roles_status = "Nadane role:\n"
            added_roles_status += f"{', '.join(added_roles)}"
            message_parts.append(added_roles_status)

        if len(removed_roles) > 0:
            removed_roles_status = "Usunięte role:\n"
            removed_roles_status += f"{', '.join(removed_roles)}"
            message_parts.append(removed_roles_status)

        if len(added_roles) == 0 and len(removed_roles) == 0:
            message_parts.append("Brak ról do nadania lub zabrania.")

        final_message = "\n".join(message_parts)
        await self._write_to_dedicated_channel(final_message)


    async def _update_auto_roles(self, payload, roles_source):
        guild = self.get_guild(payload.guild_id)
        channel_id = payload.channel_id

        if channel_id in self.config.auto_roles_channels:
            member = guild.get_member(payload.user_id)
            self.logger.info(f"Updating auto roles for user {member}")
            message_id = payload.message_id
            channel = await self.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            self.logger.debug(f"Caused by reaction on message {message.content} in channel {channel}")
            roles_to_add, roles_to_remove = roles_source(member, message)

            if len(roles_to_add) == 0 and len(roles_to_remove) == 0:
                self.logger.warning(f"No roles to be added nor removed were returned after member {member} reaction in auto roles channel for {message.content}.")

            added_roles, removed_roles = await self._update_member_roles(member, roles_to_add, roles_to_remove)
            await self._single_user_report(f"Użytkownik {member} dokonał zmian roli:", added_roles, removed_roles)


    async def _update_member_roles(self, member, roles_to_add, roles_to_remove) -> Tuple[List, List]:
        member_roles = member.roles
        member_role_names = {role.name for role in member_roles}

        added_roles = []
        removed_roles = []

        # add missing roles
        missing_roles = [add for add in roles_to_add if add not in member_role_names]

        if len(missing_roles) > 0:
            missing_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in missing_roles]
            await member.add_roles(*missing_ids)
            added_roles = missing_roles

        # remove taken roles
        redundant_roles = [remove for remove in roles_to_remove if remove in member_role_names]

        if len(redundant_roles) > 0:
            redundant_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in redundant_roles]
            await member.remove_roles(*redundant_ids)
            removed_roles = redundant_roles

        # in case of any role change action, perform a sleep to avoid rate limit
        if len(missing_roles) > 0 or len(redundant_roles) > 0:
            await asyncio.sleep(1)

        return (added_roles, removed_roles)


    async def _refresh_roles(self, members):
        self.logger.info("Refreshing roles for all users.")
        added_roles = {}
        removed_roles = {}

        for member in members:
            self.logger.debug(f"Processing user {repr(member.name)}")

            roles_to_add, roles_to_remove = self.config.roles_source.get_user_roles(member)
            self.logger.debug(f"Roles to add: {repr(roles_to_add)}, roles to remove: {repr(roles_to_remove)}")

            added, removed = await self._update_member_roles(member, roles_to_add, roles_to_remove)

            if len(added) > 0:
                added_roles[member.name] = added

            if len(removed) > 0:
                removed_roles[member.name] = removed

        self.logger.info("Print reports")
        message_parts = []

        message_parts.append("Aktualizacja ról zakończona.")
        if len(added_roles) > 0:
            added_roles_status = "Nowe role nadane użytkownikom:\n"
            for user, roles in added_roles.items():
                added_roles_status += f"{user}: {', '.join(roles)}\n"
            message_parts.append(added_roles_status)

        if len(removed_roles) > 0:
            removed_roles_status = "Role zabrane użytkownikom:\n"
            for user, roles in removed_roles.items():
                removed_roles_status += f"{user}: {', '.join(roles)}\n"
            message_parts.append(removed_roles_status)

        if len(added_roles) == 0 and len(removed_roles) == 0:
            message_parts.append("Brak zmian do wprowadzenia.")

        final_message = "\n".join(message_parts)
        final_message_escaped = escape_markdown(final_message)
        await self._write_to_dedicated_channel(final_message_escaped)
