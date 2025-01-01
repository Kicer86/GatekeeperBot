
import asyncio
import discord
import logging
import subprocess

from dataclasses import dataclass
from discord.utils import escape_markdown
from typing import Dict, List, Tuple, Set

from roles_bot.configuration import Configuration


class RolesSource:
    def invalidate_cache(self):                                                             # clear cache
        pass

    # methods to be called for known users
    def get_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:        # get roles for member. Returns (roles to be added, roles to be removed) which may be cached.
        pass

    def fetch_user_roles(self, member: discord.Member) -> Tuple[List[str], List[str]]:      # get roles for member. Returns (roles to be added, roles to be removed) omiting cache
        pass

    def get_user_auto_roles_reaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:      # get roles for member who reacted on a message in auto roles channel
        pass

    def get_user_auto_roles_unreaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:    # get roles for member who unreacted on a message in auto roles channel
        pass

    # methods for not known yet users
    def is_user_known(self, member: discord.Member) -> bool:
        pass

    def role_for_known_users(self) -> str:
        pass


@dataclass
class BotConfig:
    dedicated_channel: int                                  # channel id
    roles_source: RolesSource
    auto_roles_channels: List[int]                          # channel ids
    server_regulations_message_id: Tuple[int, int]          # channel id, message id


def get_current_commit_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        return None


class RolesBot(discord.Client):
    def __init__(self, config: BotConfig, storage_dir: str, logger):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents = intents)

        self.config = config
        self.channel = None
        self.logger = logger
        self.member_ids_accepted_regulations = []
        self.storage = Configuration(storage_dir, logging.getLogger("Configuration"))
        self.guild_id = None


    async def on_ready(self):
        hash = get_current_commit_hash()
        self.logger.info(f"Bot is ready as {self.user}. git commit: {hash}")

        if len(self.guilds) != 1:
            raise RuntimeError(f"Invalid number of guilds: {len(self.guilds)}")

        guild = self.guilds[0]
        self.guild_id = guild.id
        self.channel = await self.fetch_channel(self.config.dedicated_channel)

        self.logger.debug(f"Using channel {self.config.dedicated_channel} for notifications")

        for auto_roles_channel in self.config.auto_roles_channels:
            channel = await self.fetch_channel(auto_roles_channel)
            self.logger.debug(f"Auto roles: listening for reactions in channel {channel}")

        regulations_channel = guild.get_channel(self.config.server_regulations_message_id[0])
        acceptance_message = await regulations_channel.fetch_message(self.config.server_regulations_message_id[1])
        for reaction in acceptance_message.reactions:
            emoji = reaction.emoji
            if str(emoji) == "👍":
                self.member_ids_accepted_regulations = [user.id async for user in reaction.users()]

        bot_status = f"Start bota. git commit: {hash}\n"
        await self._write_to_dedicated_channel(bot_status)
        await self._update_state()


    async def on_message(self, message):
        if self.user in message.mentions:
            message_content = message.content.strip()
            bot_mention = f"<@{self.user.id}>"
            if message_content.startswith(bot_mention):
                if not any(role.name == "Administrator" for role in message.author.roles):
                    await message.channel.send("Tylko administrator może wydawać polecenia.")
                    return

                whole_command = message_content[len(bot_mention):].strip()
                command_splitted = whole_command.split(" ")
                command = command_splitted[0]
                args = command_splitted[1:]

                self.logger.debug(f"Got command {repr(command)} with args {repr(args)}")

                if command == "refresh":
                    async with self.channel.typing():
                        await self._refresh_roles(message.guild.members)
                elif command == "status":
                    async with self.channel.typing():
                        guild = message.guild
                        message = "Użytkownicy którzy zaakceptowali regulamin:\n"
                        allowed_members = map(guild.get_member, self.member_ids_accepted_regulations)
                        message += ", ".join(map(lambda m: f"{m.display_name} ({m.name})", allowed_members))

                        await self._write_to_dedicated_channel(message)
                elif command == "test" and len(args) > 0:
                    subcommand = args[0]
                    subargs = args[1:]
                    if subcommand == "newuser" and len(subargs) == 1:
                        user_mention = subargs[0]
                        if user_mention.startswith('<@') and user_mention.endswith('>'):
                            user_id = user_mention[2:-1]
                            if user_id.startswith('!'):  # Handles the '!'-prefixed mention for nicknames
                                user_id = user_id[1:]
                            member_id = int(user_id)
                            member = message.guild.get_member(member_id)

                            self.logger.info(f"Testing on_member_join for member {member.name}")
                            await self.on_member_join(member)


    async def on_member_join(self, member):
        self.logger.info(f"New user {repr(member.name)} joining the server.")

        known = self.config.roles_source.is_user_known(member)
        if known:
            role_to_add = self.config.roles_source.role_for_known_users()
            self.logger.debug(f"User is known. Adding new role: {role_to_add}")

            added_roles, removed_roles = await self._update_member_roles(member, [role_to_add], [])

            await self._single_user_report(f"Aktualizacja ról nowego użytkownika {member.name} zakończona.", added_roles, removed_roles)
        else:
            config = self.storage.get_config()

            unknown_notified_users = config.get("unknown_notified_users", [])
            member_id = member.id

            if member_id in unknown_notified_users:
                await self._write_to_dedicated_channel(f"Nowy użytkownik {member.name} nie istnieje w bazie. Instrukcja nie zostanie wysłana, ponieważ została wysłana już wcześniej.")
            else:
                await self._write_to_dedicated_channel(f"Użytkownik {member.name} nie istnieje w bazie. Wysyłanie instrukcji powiązania konta.")
                await member.send('Aby uzyskać dostęp do zasobów serwera należy postępować zgodnie z instrukcją zamieszczoną na serwerze, na kanale nazwanym #witaj.\n'
                                    'Twój ID (który będzie trzeba przekopiować) to:\n')
                await member.send(f'{member_id}')

                unknown_notified_users.append(member_id)

                config["unknown_notified_users"] = unknown_notified_users
                self.storage.set_config(config)


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
