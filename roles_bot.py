
import asyncio
import discord
import logging

from typing import Dict, List, Tuple


class RolesSource:
    def invalidate_cache(self):                                                             # clear cache
        pass

    def get_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:        # get roles for member. Returns (roles to be added, roles to be removed)
        pass


class RolesBot(discord.Client):
    def __init__(self, dedicated_channel: str, roles_source: RolesSource, logger):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents = intents)
        self.roles_source = roles_source
        self.channel_name = dedicated_channel
        self.channel = None
        self.logger = logger

    async def on_ready(self):
        self.logger.info(f"Bot is ready as {self.user}")

        if len(self.guilds) != 1:
            raise RuntimeError(f"Invalid number of guilds: {len(self.guilds)}")

        guild = self.guilds[0]
        self.channel = discord.utils.get(guild.channels, name=self.channel_name)

    async def on_message(self, message):
        if self.user in message.mentions and len(message.mentions) == 1:
            if not any(role.name == "Administrator" for role in message.author.roles):
                await message.channel.send("Tylko administrator może wydawać polecenia.")
                return

            if message.content == f"<@{self.user.id}> refresh":
                async with self.channel.typing():
                    await self._refresh_roles(message.guild.members)

    async def _write_to_dedicated_channel(self, message: str):
        self.logger.debug(f"Sending message {message}")
        await self.channel.send(message)

    async def _refresh_roles(self, members):
        self.logger.info("Refreshing roles")
        added_roles = {}
        removed_roles = {}

        for member in members:
            self.logger.debug(f"Processing user {member.name}")
            roles = member.roles
            role_names = {role.name for role in roles}

            roles_to_add, roles_to_remove = self.roles_source.get_user_roles(member)
            self.logger.debug(f"Roles to add: {roles_to_add}, roles to remove: {roles_to_remove}")

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

        self.logger.info("Print reports")
        message_parts = []

        message_parts.append("Aktualizacja ról zakończona.")
        if len(added_roles) > 0:
            added_roles_status = "Nowe role nadane użytkownikom:\n"
            for user, roles in added_roles.items():
                added_roles_status += f"{user}: {", ".join(roles)}\n"
            message_parts.append(added_roles_status)

        if len(removed_roles) > 0:
            removed_roles_status = "Role zabrane użytkownikom:\n"
            for user, roles in removed_roles.items():
                removed_roles_status += f"{user}: {", ".join(roles)}\n"
            message_parts.append(removed_roles_status)

        if len(added_roles) == 0 and len(removed_roles) == 0:
            message_parts.append("Brak zmian do wprowadzenia.")

        final_message = "\n".join(message_parts)
        await self._write_to_dedicated_channel(final_message)
