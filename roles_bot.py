
import asyncio
import discord
import logging
import subprocess

from dataclasses import dataclass
from discord.utils import escape_markdown
from enum import Enum
from typing import Dict, List, Tuple, Set

from roles_bot.configuration import Configuration


class UserStatusFlags(Enum):
    Known = 1
    Accepted = 2


class RolesSource:
    def invalidate_cache(self):                                                                                                 # clear cache
        pass

    def get_user_roles(self, member_id: int, flags: Dict[UserStatusFlags, bool]) -> Tuple[List[str], List[str]]:                # get roles for member. Returns (roles to be added, roles to be removed).
        pass

    def get_users_roles(self, member_ids: Dict[int, Dict[UserStatusFlags, bool]]) -> Dict[int, Tuple[List[str], List[str]]]:    # get roles for members. Returns dict of surest with tupe og roles to be added and roles to be removed
        pass

    def get_user_auto_roles_reaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:    # get roles for member who reacted on a message in auto roles channel
        pass

    def get_user_auto_roles_unreaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:  # get roles for member who unreacted on a message in auto roles channel
        pass

    def is_user_known(self, member: discord.Member) -> bool:
        pass

    def role_for_known_users(self) -> str:
        pass

    def list_known_users(self) -> Dict[str, any]:
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
        self.member_ids_accepted_regulations = set()
        self.storage = Configuration(storage_dir, logging.getLogger("Configuration"))
        self.guild_id = None
        self.unknown_users = set()


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

        async with self.channel.typing():
            await self._write_to_dedicated_channel(f"Start bota. git commit: {hash}\n")
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
                        if len(args) == 0:
                            await self._refresh_roles(message.guild.members)
                        else:
                            member_ids = [int(id) for id in args]
                            members = [message.guild.get_member(member_id) for member_id in member_ids]
                            await self._refresh_roles(members)
                elif command == "status":
                    async with self.channel.typing():
                        await self._print_status()
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
                elif command == "dump_db":
                    users_info = self.config.roles_source.list_known_users()
                    status = "List znanych userów z bazy danych:\n"

                    for user, data in users_info.items():
                        if user.isnumeric():
                            # assume id
                            member_id = int(user)
                            member = message.guild.get_member(member_id)
                            status += f"{member.display_name} ({member.name}, {member_id})"
                        else:
                            # assume direct user name
                            status += f"{user}"

                        status += f": {data}\n"

                    await self._write_to_dedicated_channel(status)


    async def on_member_join(self, member):
        self.logger.info(f"New user {repr(member.name)} joining the server.")

        known = self.config.roles_source.is_user_known(member.id)
        if known:
            added_roles, removed_roles = await self._update_member_roles(member)
            await self._single_user_report(f"Aktualizacja ról nowego użytkownika {member.name} zakończona.", added_roles, removed_roles)
        else:
            self.unknown_users.add(member.id)
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
        await self._check_reaction_on_regulations(payload, True)


    async def on_raw_reaction_remove(self, payload):
        await self._update_auto_roles(payload, self.config.roles_source.get_user_auto_roles_unreaction)
        await self._check_reaction_on_regulations(payload, False)


    def _split_message(self, message: str) -> [str]:
        fragment_length: int = 2000
        message_fragments: [str] = []
        split_priorities = ['\n', '.', ',', ' ']

        begin: int = 0
        while begin < len(message):
            fragment = ""
            end = begin + fragment_length

            if end > len(message):
                # If we are at the end of the message, take the remaining text
                fragment = message[begin:]
            else:
                # Try to split at the highest-priority character first
                closest_split = -1
                for split_char in split_priorities:
                    closest_split = message.rfind(split_char, begin, end)
                    if closest_split != -1:
                        break  # Stop as soon as we find a suitable split point

                if closest_split == -1:
                    # If no split points are found, fallback to splitting at the limit
                    fragment = message[begin:end]
                else:
                    # Include the splitting character in the fragment
                    fragment = message[begin:closest_split + 1]

            # Add the fragment to the list and move the pointer
            message_fragments.append(fragment.strip())
            begin += len(fragment)

        return message_fragments


    async def _write_to_dedicated_channel(self, message: str):
        self.logger.debug(f"Sending message {repr(message)}")

        message_splitted = self._split_message(message)

        for part in message_splitted:
            await self.channel.send(part)


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

            added_roles, removed_roles = await self._apply_member_roles(member, roles_to_add, roles_to_remove)
            await self._single_user_report(f"Użytkownik {member} dokonał zmian roli:", added_roles, removed_roles)


    async def _check_reaction_on_regulations(self, payload, added: bool):
        """
            Check if reaction happened on regulations acceptance message and react accordingly if so
        """
        channel_id = payload.channel_id
        if channel_id != self.config.server_regulations_message_id[0]:
            return

        message_id = payload.message_id
        if message_id != self.config.server_regulations_message_id[1]:
            return

        guild = self.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        self.logger.info(f"User {member.name} reacted on regulations message")

        if added:
            self.member_ids_accepted_regulations.add(member.id)
            await self._write_to_dedicated_channel(f"Użytkownik {member.display_name} zaakceptował regulamin.")
        else:
            self.member_ids_accepted_regulations.remove(member.id)
            await self._write_to_dedicated_channel(f"Użytkownik {member.display_name} odrzucił regulamin.")

        added_roles, removed_roles = await self._update_member_roles(member)
        await self._single_user_report(f"Aktualizacja ról użytkownika {member.name} zakończona.", added_roles, removed_roles)


    async def _update_member_roles(self, member: discord.Member) -> Tuple[List, List]:
        flags = self._build_user_flags(member.id)
        roles_to_add, roles_to_remove = self.config.roles_source.get_user_roles(member.id, flags)
        self.logger.debug(f"Roles to add: {repr(roles_to_add)}, roles to remove: {repr(roles_to_remove)}")

        added, removed = await self._apply_member_roles(member, roles_to_add, roles_to_remove)

        return added, removed


    async def _apply_member_roles(self, member: discord.Member, roles_to_add, roles_to_remove) -> Tuple[List, List]:
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

        return (added_roles, removed_roles)


    def _build_user_flags(self, member_id: int) -> Dict[UserStatusFlags, bool]:
        flags = {}
        flags[UserStatusFlags.Known] = False if member_id in self.unknown_users else True
        flags[UserStatusFlags.Accepted] = True if member_id in self.member_ids_accepted_regulations else False
        return flags


    async def _refresh_roles(self, members: List[discord.Member]):
        """
            Iterate over given set of members and update their roles.
        """
        self.logger.info(f"Refreshing roles for {len(members)} users.")
        added_roles = {}
        removed_roles = {}
        guild = self.get_guild(self.guild_id)

        users_query = {member.id: self._build_user_flags(member.id) for member in members}
        new_roles = self.config.roles_source.get_users_roles(users_query)

        for member_id, roles in new_roles.items():
            member = guild.get_member(member_id)
            self.logger.debug(f"Processing user {repr(member.name)}")

            add = roles[0]
            remove = roles[1]

            added, removed = await self._apply_member_roles(member, add, remove)

            if len(added) > 0:
                added_roles[member.name] = added

            if len(removed) > 0:
                removed_roles[member.name] = removed

            if len(added) > 0 and len(removed) > 0:
                # in case of any role change action, perform a sleep to avoid rate limit
                await asyncio.sleep(0.2)

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


    async def _print_status(self):
        """
            Print bot status
        """

        guild = self.get_guild(self.guild_id)
        state = "Obecny stan:\n"

        unknown_user_names = [guild.get_member(member_id).name for member_id in self.unknown_users]
        state += f"Nieznani użytkownicy: {', '.join(unknown_user_names)}\n"

        state += "Użytkownicy którzy zaakceptowali regulamin:\n"
        allowed_members = map(guild.get_member, self.member_ids_accepted_regulations)
        state += ", ".join(map(lambda m: f"{m.display_name} ({m.name})", allowed_members))

        await self._write_to_dedicated_channel(state)


    async def _update_state(self):
        """
            Method collects and updates bot's information about server state.

            It is meant to be used on bot startup to get the lay of the land.
            It can also be used by a manual refresh if things get out of sync for any reason.
        """

        self.unknown_users = self._collect_unknown_users()
        self.member_ids_accepted_regulations = await self._collect_users_accepting_regulations()
        await self._print_status()


    def _collect_unknown_users(self) -> set[int]:
        """
            Method collects unknown users (not recognized by the RolesSource) on the server.
        """

        known_user_role_name = self.config.roles_source.role_for_known_users()
        guild = self.get_guild(self.guild_id)

        known_user_role = discord.utils.get(guild.roles, name=known_user_role_name)
        members_without_role = {member.id for member in guild.members if known_user_role not in member.roles}

        return members_without_role


    async def _collect_users_accepting_regulations(self) -> Set[int]:
        """
            Collect users who accepted regulations
        """
        guild = self.get_guild(self.guild_id)
        regulations_channel = guild.get_channel(self.config.server_regulations_message_id[0])
        acceptance_message = await regulations_channel.fetch_message(self.config.server_regulations_message_id[1])
        members = []

        for reaction in acceptance_message.reactions:
            emoji = reaction.emoji
            if str(emoji) == "👍":
                members = {user.id async for user in reaction.users()}

        return members
