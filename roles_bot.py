
import asyncio
import discord
import logging

from typing import Dict, List, Tuple, Set


class RolesSource:
    def invalidate_cache(self):                                                             # clear cache
        pass

    def get_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:        # get roles for member. Returns (roles to be added, roles to be removed) which may be cached.
        pass

    def fetch_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:      # get roles for member. Returns (roles to be added, roles to be removed) omiting cache
        pass

    def get_user_auto_roles_reaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:      # get roles for member who reacted on a message in auto roles channel
        pass

    def get_user_auto_roles_unreaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:    # get roles for member who unreacted on a message in auto roles channel
        pass


class RolesBot(discord.Client):
    def __init__(self, dedicated_channel: int, roles_source: RolesSource, auto_roles_channels: List[int], logger):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents = intents)
        self.roles_source = roles_source
        self.channel_id = dedicated_channel
        self.auto_roles_channels = auto_roles_channels
        self.channel = None
        self.logger = logger


    async def on_ready(self):
        self.logger.info(f"Bot is ready as {self.user}")

        if len(self.guilds) != 1:
            raise RuntimeError(f"Invalid number of guilds: {len(self.guilds)}")

        guild = self.guilds[0]
        self.channel = await self.fetch_channel(self.channel_id)

        self.logger.debug(f"Using channel {self.channel} for notifications")

        for auto_roles_channel in self.auto_roles_channels:
            channel = await self.fetch_channel(auto_roles_channel)
            self.logger.debug(f"Auto roles: listening for reactions in channel {channel}")


    async def on_message(self, message):
        if self.user in message.mentions and len(message.mentions) == 1:
            if not any(role.name == "Administrator" for role in message.author.roles):
                await message.channel.send("Tylko administrator może wydawać polecenia.")
                return

            if message.content == f"<@{self.user.id}> refresh":
                async with self.channel.typing():
                    await self._refresh_roles(message.guild.members)


    async def on_member_join(self, member):
        self.logger.info(f"Applying roles for new user: {member.name}.")
        roles_to_add, roles_to_remove = self.roles_source.fetch_user_roles(member)
        self.logger.debug(f"Roles to add: {roles_to_add}, roles to remove: {roles_to_remove}")

        added_roles, removed_roles = await self._update_member_roles(member, roles_to_add, roles_to_remove)

        await self._single_user_report(f"Aktualizacja ról nowego użytkownika {member.name} zakończona.", list(added_roles), list(removed_roles))


    async def on_raw_reaction_add(self, payload):
        await self._update_auto_roles(payload, self.roles_source.get_user_auto_roles_reaction)


    async def on_raw_reaction_remove(self, payload):
        await self._update_auto_roles(payload, self.roles_source.get_user_auto_roles_unreaction)


    async def _write_to_dedicated_channel(self, message: str):
        self.logger.debug(f"Sending message {message}")
        await self.channel.send(message)


    async def _single_user_report(self, title: str, added_roles: List[str], removed_roles: List[str]):
        self.logger.info("Print report")
        message_parts = []

        message_parts.append(title)
        if len(added_roles) > 0:
            added_roles_status = "Nadane role:\n"
            added_roles_status += f"{', '.join(added_roles)}\n"
            message_parts.append(added_roles_status)

        if len(removed_roles) > 0:
            removed_roles_status = "Zabrane role:\n"
            removed_roles_status += f"{', '.join(removed_roles)}\n"
            message_parts.append(removed_roles_status)

        if len(added_roles) == 0 and len(removed_roles) == 0:
            message_parts.append("Brak ról do nadania lub zabrania.")

        final_message = "\n".join(message_parts)
        await self._write_to_dedicated_channel(final_message)


    async def _update_auto_roles(self, payload, roles_source):
        guild = self.get_guild(payload.guild_id)
        channel_id = payload.channel_id

        if channel_id in self.auto_roles_channels:
            member = guild.get_member(payload.user_id)
            self.logger.info(f"Updating auto roles for user {member}")
            message_id = payload.message_id
            channel = await self.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            self.logger.debug(f"Caused by reaction on message {message.content} in channel {channel}")
            roles_to_add, roles_to_remove = roles_source(member, message)

            if len(roles_to_add) == 0 and len(roles_to_remove) == 0:
                self.logger.warning(f"No roles to be added nor removed were returned after member {member} reaction in auto roles channel for {message.content}.")

            await self._update_member_roles(member, roles_to_add, roles_to_remove)
            await self._single_user_report(f"Użytkownik {member} dokonał zmian roli:", roles_to_add, roles_to_remove)


    async def _update_member_roles(self, member, roles_to_add, roles_to_remove) -> Tuple[Set, Set]:
        roles = member.roles
        role_names = {role.name for role in roles}

        added_roles = {}
        removed_roles = {}

        # add missing roles
        missing = [add for add in roles_to_add if add not in role_names]

        if len(missing) > 0:
            missing_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in missing]
            await member.add_roles(*missing_ids)
            added_roles[member.name] = missing

        # remove taken roles
        redundant = [remove for remove in roles_to_remove if remove in role_names]

        if len(redundant) > 0:
            redundant_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in redundant]
            await member.remove_roles(*redundant_ids)
            removed_roles[member.name] = redundant

        # in case of any role change action, perform a sleep to avoid rate limit
        if len(missing) > 0 or len(redundant) > 0:
            await asyncio.sleep(1)

        return (added_roles, removed_roles)


    async def _refresh_roles(self, members):
        self.logger.info("Refreshing roles for all users.")
        added_roles = {}
        removed_roles = {}

        for member in members:
            self.logger.debug(f"Processing user {member.name}")

            roles_to_add, roles_to_remove = self.roles_source.get_user_roles(member)
            self.logger.debug(f"Roles to add: {roles_to_add}, roles to remove: {roles_to_remove}")

            added, removed = await self._update_member_roles(member, roles_to_add, roles_to_remove)
            added_roles.update(added)
            removed_roles.update(removed)

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
        await self._write_to_dedicated_channel(final_message)
