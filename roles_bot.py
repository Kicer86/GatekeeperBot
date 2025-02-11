
import asyncio
import discord
import logging
import subprocess

from dataclasses import dataclass
from datetime import datetime, timedelta
from discord.utils import escape_markdown
from discord.ext import tasks
from enum import Enum
from typing import Any, Dict, List, Tuple, Set

from . import utils
from roles_bot.configuration import Configuration


class UserStatusFlags(Enum):
    Known = 1
    Accepted = 2


class RolesSource:
    def get_user_roles(self, member: discord.Member, flags: Dict[UserStatusFlags, bool]) -> Tuple[List[str], List[str]]:                # get roles for member. Returns (roles to be added, roles to be removed).
        pass

    def get_users_roles(self, members: Dict[discord.Member, Dict[UserStatusFlags, bool]]) -> Dict[int, Tuple[List[str], List[str]]]:    # get roles for members. Returns dict of surest with tupe og roles to be added and roles to be removed
        pass

    def get_user_auto_roles_reaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:    # get roles for member who reacted on a message in auto roles channel
        pass

    def get_user_auto_roles_unreaction(self, member: discord.Member, message: discord.Message) -> Tuple[List[str], List[str]]:  # get roles for member who unreacted on a message in auto roles channel
        pass

    def role_for_known_users(self) -> str:
        pass

    def list_known_users(self) -> Dict[str, Any]:
        pass


class NicknamesSource:
    def get_nicknames_for(self, member_ids: List[int]) -> Dict[str, str]:
        pass

    def get_all_nicknames(self) -> Dict[str, str]:
        pass


@dataclass
class BotConfig:
    dedicated_channel: int                                  # channel id
    roles_source: RolesSource
    nicknames_source: NicknamesSource
    auto_roles_channels: List[int]                          # channel ids
    server_regulations_message_ids: List[Tuple[int, int]]   # list of (channel id, message id)
    user_auto_refresh_roles_message_id: Tuple[int, int]     # channel id, message id
    ids_channel_id: int                                     # channel to put user ids
    guild_id: int                                           # allowed guild ID


def get_current_commit_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        return None


class RolesBot(discord.Client):
    AutoRefreshEntry = "autorefresh"
    VerbosityEntry = "verbosity"
    IDEntry = "bot_id"
    DryRunEntry = "dry_run"
    UnknownNotifiedUsers = "unknown_notified_users"

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
        self.last_auto_refresh = datetime.now()
        self.message_prefix = self.storage.get_config().get("message_prefix", "")

        # setup default values in config
        self.storage.set_default(RolesBot.AutoRefreshEntry, 1440)
        self.storage.set_default(RolesBot.VerbosityEntry, logging.INFO)
        self.storage.set_default(RolesBot.IDEntry, 1)
        self.storage.set_default(RolesBot.DryRunEntry, False)

        # read bot's config from file
        self.bot_id = self.storage.get_config().get(RolesBot.IDEntry)
        self.dry_run = self.storage.get_config().get(RolesBot.DryRunEntry)


    async def on_ready(self):
        hash = get_current_commit_hash()
        self.logger.info(f"Bot is ready as {self.user}. git commit: {hash}. Dry run: {self.dry_run}")

        if len(self.guilds) != 1:
            self.logger.error(f"Invalid number of guilds: {len(self.guilds)}")
            await self.close()
            return

        guild = self.guilds[0]
        self.guild_id = guild.id

        if self.guild_id != self.config.guild_id:
            self.logger.error(f"Leaving unauthorized guild: {guild.name} ({guild.id})")
            await guild.leave()
            return

        self.channel = await self.fetch_channel(self.config.dedicated_channel)

        self.logger.debug(f"Using channel {self.config.dedicated_channel} for notifications")

        for auto_roles_channel in self.config.auto_roles_channels:
            channel = await self.fetch_channel(auto_roles_channel)
            self.logger.debug(f"Auto roles: listening for reactions in channel {channel}")

        async with self.channel.typing():
            await self._write_to_dedicated_channel(f"Start bota. git commit: {hash} ID: **{self.bot_id}**\n")

            if self.dry_run:
                await self._write_to_dedicated_channel(f"**Tryb dry-run aktywny**\n", logging.WARNING)

            await self._update_state()

        self._auto_refresh.start()


    async def on_guild_join(self, guild):
        if guild.id != self.config.guild_id:
            self.logger.error(f"Leaving unauthorized guild: {guild.name} ({guild.id})")
            await guild.leave()


    async def on_message(self, message: discord.Message):
        author = message.author
        message_guild = message.guild
        if message_guild is None:
            self.logger.info(f"Ignoring private message from user {repr(author.name)}: {repr(message.content)}")
            return

        if message_guild.id != self.guild_id:
            self.logger.error(f"Got message from guild '{message_guild}', which is not the current one. This should never happen.")
            return

        if self.user in message.mentions:
            message_content = message.content.strip()
            bot_mention = f"<@{self.user.id}>"

            if message_content.startswith(bot_mention):
                if not any(role.name in ["Administrator", "Technik"] for role in author.roles):
                    self.logger.warning(f"User {author.name} has no rights to use bot.")
                    return

                guild = message_guild
                whole_command = message_content[len(bot_mention):].strip()
                command_splitted = whole_command.split(" ")

                # check for ID filter
                if len(command_splitted) == 0:
                    self.logger.debug(f"No command. Ignoring")
                    return

                first_arg: str = command_splitted[0]
                if first_arg.isdigit():
                    id = int(first_arg)
                    if id != self.bot_id:
                        self.logger.debug(f"Message for bot with id: {id}. My id: {self.bot_id}. Ignoring")
                        return

                    # id matched, skip it now
                    command_splitted = command_splitted[1:]

                # check command
                if len(command_splitted) == 0:
                    self.logger.debug(f"No command. Ignoring")
                    return

                command = command_splitted[0]
                args = command_splitted[1:]

                self.logger.debug(f"Got command {repr(command)} with args {repr(args)}")

                if command == "refresh":
                    async with self.channel.typing():
                        if len(args) == 0:
                            await self._refresh_roles(guild.members)
                        else:
                            try:
                                member_ids = [int(id) for id in args]
                            except ValueError:
                                await self._write_to_dedicated_channel("Argumenty muszą być numerami ID")
                            else:
                                members = [guild.get_member(member_id) for member_id in member_ids]
                                await self._refresh_roles(members)
                                await self._refresh_names(member_ids)
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
                            member = guild.get_member(member_id)

                            self.logger.info(f"Testing on_member_join for member {member.name}")
                            await self.on_member_join(member)
                    elif subcommand == "del_emo" and len(subargs) == 3:
                        channel_id = int(subargs[0])
                        message_id = int(subargs[1])
                        member_id = int(subargs[2])
                        message = await utils.get_message(channel_id, message_id)
                        status = await utils.remove_user_reactions(message_guild, message, member_id)
                elif command == "dump_db":
                    users_membership = self.config.roles_source.list_known_users()
                    users_names =  self.config.nicknames_source.get_all_nicknames()
                    status = "List znanych userów z bazy danych:\n"

                    for user, data in users_membership.items():
                        if user.isnumeric():
                            # assume id
                            member_id = int(user)
                            member_details = await self._build_user_details(guild, member_id)
                            status += member_details
                        else:
                            # assume direct user name
                            status += f"{user}"

                        nickname = users_names.get(user, None)
                        display_nickname = "EMPTY" if nickname is None else "\\*" * len(nickname)
                        status += f": {data} -> {display_nickname}\n"

                    await self._write_to_dedicated_channel(status)
                elif command == "set" and len(args) > 0:
                    subcommand = args[0]
                    subargs = args[1:]
                    if subcommand == "autorefresh" and len(subargs) == 1:
                        async with self.channel.typing():
                            autorefresh = int(subargs[0])
                            if autorefresh >= 5:
                                config = self.storage.get_config()
                                current_value = config[RolesBot.AutoRefreshEntry]
                                config[RolesBot.AutoRefreshEntry] = autorefresh
                                self.storage.set_config(config)
                                self.logger.info(f"Changing auto refresh {current_value} -> {autorefresh} minutes")
                                await self._write_to_dedicated_channel(f"Częstotliwość odświeżania zmieniona na {autorefresh} minut")
                            else:
                                await self._write_to_dedicated_channel(f"Daj minimum 5 minut")
                    elif subcommand == "verbosity" and len(subargs) == 1:
                        async with self.channel.typing():
                            verbosity = int(subargs[0])

                            config = self.storage.get_config()
                            current_value = config[RolesBot.VerbosityEntry]
                            config[RolesBot.VerbosityEntry] = verbosity
                            self.storage.set_config(config)
                            self.logger.info(f"Changing verbosity {current_value} -> {verbosity}")
                            await self._write_to_dedicated_channel(f"Poziom gadatliwości bota zmieniony na: {verbosity}")
                elif command == "set_role" and len(args) >= 3:
                    user_id = int(args[0])
                    state = True if args[1] == "1" else False
                    role_name = " ".join(args[2:])
                    member = message_guild.get_member(user_id)
                    if state:
                        await self._apply_member_roles(member, [role_name], [])
                    else:
                        await self._apply_member_roles(member, [], [role_name])

                elif command == "help":
                    async with self.channel.typing():
                        await self._write_to_dedicated_channel("Dostepne polecenia:\n"
                                                               "```\n"
                                                               "refresh [ID1 ID2 ...]               - odświeża role użytkowników których ID podane są jako argumenty. Przy braku argumentów odświeżani są wszyscy.\n"
                                                               "status                              - wyświetla stan bota\n"
                                                               "test newuser @user                  - testuje procedurę dołączenia nowego użytkownika na użytkowniku @user\n"
                                                               "test del_emo ch_id msg_id usr_id    - usuwa reakcje podanego usera spod wiadomości\n"
                                                               "dump_db                             - zrzuca treść bazy danych\n"
                                                               "set autorefresh czas                - zmienia częstotliwość auto odświeżania ról na 'czas' minut (co najmniej 5)\n"
                                                               "set verbosity poziom                - zmienia poziom gadatliwości bota. Wartości odpowiadają stałym poziomów logowania modułu 'logging' Pythona\n"
                                                               "\n"
                                                               "Polecenie może być poprzedzone ID bota (zdefiniowanym w pliku konfiguracyjnym), aby wysyłać komendy do konkretnej instancji bota.\n"
                                                               "```"
                                                              )


    async def on_member_join(self, member: discord.Member):
        self.logger.info(f"New user {repr(member.name)} joining the server.")

        added_roles, removed_roles = await self._update_member_roles(member)
        await self._single_user_report(f"Aktualizacja ról nowego użytkownika {member.name} zakończona.", added_roles, removed_roles)

        user_roles = member.roles
        user_roles_names = [role.name for role in user_roles]
        known_users_role = self.config.roles_source.role_for_known_users()

        user_is_known = known_users_role in user_roles_names

        if user_is_known:
            self.logger.info("User is known")
        else:
            self.logger.info("User is not known")
            self.unknown_users.add(member.id)
            config = self.storage.get_config()

            unknown_notified_users = config.get(RolesBot.UnknownNotifiedUsers, {})
            if isinstance(unknown_notified_users, list):
                unknown_notified_users = dict.fromkeys(unknown_notified_users, None)

            member_id = member.id
            member_id_str = str(member_id)

            guild = self.get_guild(self.guild_id)
            discord_name, log_name = await utils.build_user_name(self, guild, member_id)

            if member_id_str in unknown_notified_users:
                await self._write_to_dedicated_channel(f"Nowy użytkownik {discord_name} nie istnieje w bazie. Instrukcja nie zostanie wysłana, ponieważ została wysłana już wcześniej.")
            else:
                await self._write_to_dedicated_channel(f"Użytkownik {discord_name} nie istnieje w bazie. Wysyłanie ID na dedykowany kanał.")

                if self.dry_run:
                    self.logger.debug(f"Dry run, not sending ID for the user {log_name}")
                else:
                    channel = guild.get_channel(self.config.ids_channel_id)
                    msg1: discord.Message = await channel.send(f"{member.mention} Twoje ID to:")
                    msg2: discord.Message = await channel.send(f"{member.id}")

                    unknown_notified_users[member_id_str] = {"channel": channel.id, "messages": [msg1.id, msg2.id]}
                    config[RolesBot.UnknownNotifiedUsers] = unknown_notified_users

            self.storage.set_config(config)

    async def on_member_remove(self, member: discord.Member):
        guild = self.get_guild(self.guild_id)
        discord_name, log_name = await utils.build_user_name(self, guild, member)

        self.logger.info(f"User {log_name} left guild")
        await self._write_to_dedicated_channel(f"Użytkownik {discord_name} opuścił serwer", logging.INFO)
        await self._user_becomes_unknown(member)


    async def on_raw_reaction_add(self, payload):
        await self._update_auto_roles(payload, self.config.roles_source.get_user_auto_roles_reaction)
        await self._check_reaction_on_regulations(payload, True)
        await self._check_autorefresh(payload)


    async def on_raw_reaction_remove(self, payload):
        await self._update_auto_roles(payload, self.config.roles_source.get_user_auto_roles_unreaction)
        await self._check_reaction_on_regulations(payload, False)


    def _split_message(self, message: str) -> List[str]:
        fragment_length: int = 2000 - len(self.message_prefix) - 1
        message_fragments: List[str] = []
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


    def _is_level_sufficent_for_send(self, level: int) -> bool:
        allowed_level = self.storage.get_config()[RolesBot.VerbosityEntry]
        send = level >= allowed_level

        return send


    async def _write_to_dedicated_channel(self, message: str, level: int = logging.INFO):
        send = self._is_level_sufficent_for_send(level)

        if send:
            self.logger.debug(f"Sending {level} level message {repr(message)}")

            message_splitted = self._split_message(message)

            prefix = "" if self.message_prefix == "" else self.message_prefix + " "

            for part in message_splitted:
                await self.channel.send(prefix + part)
        else:
            self.logger.debug(f"Not Sending {level} level message {repr(message)}")


    @tasks.loop(seconds = 60)
    async def _auto_refresh(self):
        now = datetime.now()
        time_since_last_auto_refresh = now - self.last_auto_refresh

        refresh_delta = self.storage.get_config()[RolesBot.AutoRefreshEntry]

        if time_since_last_auto_refresh >= timedelta(minutes = refresh_delta):
            self.logger.info("Auto refresh condition triggered")
            await self._write_to_dedicated_channel("Automatyczne odświeżanie ról (timer event).")
            self.last_auto_refresh = now

            guild = self.get_guild(self.guild_id)
            await self._refresh_roles(guild.members)
            user_ids = [member.id for member in guild.members]
            await self._refresh_names(user_ids)


    async def _single_user_report(self, title: str, added_roles: List[str], removed_roles: List[str]):
        """
            Report to dedicated channel about role changes that happened to the member
        """
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
        """
            Apply roles user has chosen by reacting to certain messages
        """
        guild = self.get_guild(payload.guild_id)
        channel_id = payload.channel_id

        if channel_id in self.config.auto_roles_channels:
            member_id = payload.user_id
            message_id = payload.message_id

            member = guild.get_member(member_id)
            name_for_discord, name_for_log = await utils.build_user_name(self, guild, member)

            self.logger.info(f"Updating auto roles for user {name_for_log}")
            channel = await self.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            self.logger.debug(f"Caused by reaction on message {message.content} in channel {channel}")
            roles_to_add, roles_to_remove = roles_source(member, message)

            if len(roles_to_add) == 0 and len(roles_to_remove) == 0:
                self.logger.warning(f"No roles to be added nor removed were returned after member {name_for_log} reaction in auto roles channel for {message.content}.")

            added_roles, removed_roles = await self._apply_member_roles(member, roles_to_add, roles_to_remove)
            await self._single_user_report(f"Użytkownik {name_for_discord} dokonał zmian roli:", added_roles, removed_roles)


    async def _check_reaction_on_regulations(self, payload, added: bool):
        """
            Check if reaction happened on regulations acceptance message and react accordingly if so
        """
        channel_id = payload.channel_id
        message_id = payload.message_id

        full_id = (channel_id, message_id)

        if full_id not in self.config.server_regulations_message_ids:
            return

        guild = self.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        self.logger.info(f"User {member.name} reacted on regulations message: {channel_id}/{message_id}")

        current_list_of_users = self.member_ids_accepted_regulations
        new_list_of_users = await self._collect_users_who_accepted_all_regulations()

        removed_acceptance = current_list_of_users - new_list_of_users
        added_acceptance = new_list_of_users - current_list_of_users

        self.member_ids_accepted_regulations = new_list_of_users

        affected_users = []

        for added in added_acceptance:
            member = guild.get_member(added)
            await self._write_to_dedicated_channel(f"Użytkownik {member.display_name} zaakceptował regulamin w całości.")
            affected_users.append(member)

        for removed in removed_acceptance:
            member = guild.get_member(removed)
            await self._write_to_dedicated_channel(f"Użytkownik {member.display_name} odrzucił regulamin (lub jego fragment).")
            affected_users.append(member)

        if len(affected_users) > 1:
            self.logger.warning(f"There was one change expected, yet got {len(affected_users)}")

        for member in affected_users:
            added_roles, removed_roles = await self._update_member_roles(member)
            await self._single_user_report(f"Aktualizacja ról użytkownika {member.name} zakończona.", added_roles, removed_roles)

        if len(added_acceptance) > 0:
            await self._refresh_names(added_acceptance)

        if len(removed_acceptance) > 0:
            members = utils.get_members(guild, removed_acceptance)
            await self._reset_names(members)


    async def _check_autorefresh(self, payload):
        """
            Check if reaction happened on roles autorefresh message, and do refresh if it did
        """
        channel_id = payload.channel_id
        if channel_id != self.config.user_auto_refresh_roles_message_id[0]:
            return

        message_id = payload.message_id
        if message_id != self.config.user_auto_refresh_roles_message_id[1]:
            return

        guild = self.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        self.logger.info(f"User {member.name} reacted on autorefresh message.")

        added_roles, removed_roles = await self._update_member_roles(member)
        await self._single_user_report(f"Użytkownik {member.display_name} zareagował na wiadomość autoodświeżenia ról.", added_roles, removed_roles)

        #  At this point user should be allowed to accept regulations.
        #  Send private message to remind user about it
        flags = self._build_user_flags(member.id)
        known = flags[UserStatusFlags.Known]
        accepted = flags[UserStatusFlags.Accepted]

        if known and not accepted:
            self.logger.info(f"User {member.name} is known but has not accepted regulations yet. Sending reminder.")
            await self._write_to_dedicated_channel(f"Wysyłanie przypomnienia użytkownikowi {member.display_name} ({member.name}) o akceptacji regulaminu.")
            await member.send("Został Ci przyznany dostęp do serwera. Teraz tylko przeczytaj i **zaakceptuj** regulamin, aby w pełni korzystać z dostępnych kanałów")


    async def _update_member_roles(self, member: discord.Member) -> Tuple[List, List]:
        """
            Check what roles should be applied to the single user and apply them.

            This function is meant to be used by one timne actions
        """
        flags = self._build_user_flags(member.id)
        roles_to_add, roles_to_remove = self.config.roles_source.get_user_roles(member, flags)
        self.logger.debug(f"Roles to add: {repr(roles_to_add)}, roles to remove: {repr(roles_to_remove)}")

        added, removed = await self._apply_member_roles(member, roles_to_add, roles_to_remove)

        return added, removed


    async def _apply_member_roles(self, member: discord.Member, roles_to_add: List[str], roles_to_remove: List[str]) -> Tuple[List[str], List[str]]:
        """
            Apply given roles to the user
        """
        member_roles = member.roles
        member_role_names = {role.name for role in member_roles}

        added_roles = []
        removed_roles = []

        issues = ""

        # add missing roles
        missing_roles = [add for add in roles_to_add if add not in member_role_names]

        if len(missing_roles) > 0:
            missing_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in missing_roles]
            try:
                if self.dry_run:
                    self.logger.debug("Dry run mode, not applying roles")
                else:
                    await member.add_roles(*missing_ids)
            except discord.errors.Forbidden:
                self.logger.warning("Some roles could not be applied")
                issues += f"**Brak uprawnień aby nadać (niektóre) role użytkownikowi {member.display_name} ({member.name})**\n"
            added_roles = missing_roles

        # remove taken roles
        redundant_roles = [remove for remove in roles_to_remove if remove in member_role_names]

        if len(redundant_roles) > 0:
            redundant_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in redundant_roles]
            try:
                if self.dry_run:
                    self.logger.debug("Dry run mode, not applying roles")
                else:
                    await member.remove_roles(*redundant_ids)
            except discord.errors.Forbidden:
                self.logger.warning("Some roles could not be taken")
                issues += f"**Brak uprawnień aby zabrać (niektóre) role użytkownikowi {member.display_name} ({member.name})**\n"

            removed_roles = redundant_roles

        if issues:
            await self._write_to_dedicated_channel(issues)

        if self.config.roles_source.role_for_known_users() in added_roles:
            # user is known now
            await self._user_becomes_known(member.id)

        if self.config.roles_source.role_for_known_users() in removed_roles:
            # user is unknown now
            await self._user_becomes_unknown(member)

        return (added_roles, removed_roles)


    async def _user_becomes_known(self, member_id: int):
        config = self.storage.get_config()
        notified_users = config.get(RolesBot.UnknownNotifiedUsers, {})

        member_id_str = str(member_id)

        if member_id_str in notified_users:
            messages_info = notified_users[member_id_str]

            if messages_info is not None:
                guild = self.get_guild(self.guild_id)
                channel_id = messages_info["channel"]
                messages_ids = messages_info["messages"]

                channel: discord.TextChannel = guild.get_channel(channel_id)
                try:
                    messages = [await channel.fetch_message(messages_id) for messages_id in messages_ids]
                    await channel.delete_messages(messages)
                except:
                    pass

            del notified_users[member_id_str]
            config[RolesBot.UnknownNotifiedUsers] = notified_users

            self.storage.set_config(config)


    async def _user_becomes_unknown(self, member: discord.Member):
        await self._reset_names([member])
        await self._revoke_user_acceptances(member)


    async def _revoke_user_acceptances(self, member: discord.Member):
        guild = self.get_guild(self.guild_id)
        discord_name, log_name = await utils.build_user_name(self, guild, member)

        self.logger.info(f"Removing acceptance of regulations for user {log_name}")
        await self._write_to_dedicated_channel(f"Usuwanie akceptacji regulaminu użytkownika {discord_name}", logging.INFO)

        for channel_id, message_id in self.config.server_regulations_message_ids:
            message = await utils.get_message(guild, channel_id, message_id)
            await utils.remove_user_reactions(guild, message, member.id)


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

        users_query = {member: self._build_user_flags(member.id) for member in members}
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
        await self._write_to_dedicated_channel(final_message_escaped, logging.DEBUG)


    async def _refresh_names(self, ids: List[int]):
        users_with_accepted_regulations = self.member_ids_accepted_regulations
        users_to_proceed = set(ids) & users_with_accepted_regulations

        if len(users_to_proceed) == 0:
            self.logger.warning("No users to refresh their names")
            return

        names = self.config.nicknames_source.get_nicknames_for(users_to_proceed)
        guild = self.get_guild(self.guild_id)

        renames = "Zmiany nicków:\n"

        nickname_changes = ""
        for id, name in names.items():
            member_id = int(id)
            member = guild.get_member(member_id)
            _, log_name = await utils.build_user_name(self, guild, member)
            self.logger.debug(f"Preparing for refresh of {log_name}")

            if member.display_name == name:
                self.logger.debug(f"Name already valid: {member.display_name} == {name}")
            else:
                self.logger.info(f"Renaming {member.display_name} ({member.name}) to {name}")
                if self.dry_run:
                    self.logger.debug("Dry run mode, not changing name")
                else:
                    await member.edit(nick = name)
                nickname_changes += f"{member.display_name} ({member.name}) -> {name}\n"

        if len(nickname_changes) == 0:
            nickname_changes = "brak"

        renames += nickname_changes

        await self._write_to_dedicated_channel(renames, logging.DEBUG)


    async def _reset_names(self, members: List[discord.Member]):
        renames = "Resetowanie nicków:\n"

        for member in members:
            self.logger.info(f"Renaming {member.display_name} ({member.name}) to {member.name}")
            try:
                await member.edit(nick = member.name)
            except discord.errors.Forbidden:
                renames += f"{member.display_name} ({member.name}) -> {member.name} (**Nieskuteczne, brak uprawnień**)\n"
            except discord.errors.NotFound:
                renames += f"{member.display_name} ({member.name}) -> {member.name} (**Nieskuteczne, użytkownik opuścił serwer**)\n"
            else:
                renames += f"{member.display_name} ({member.name}) -> {member.name}\n"

        await self._write_to_dedicated_channel(renames, logging.DEBUG)


    async def _build_user_details(self, guild: discord.Guild, id: int) -> str:
        status = await utils.get_user_status(self, guild, id)
        name, _ = await utils.build_user_name(self, guild, id)

        result: str = ""

        if status is None:
            result = ":black_circle:"
        elif status:
            result = ":green_circle:"
        else:
            result = ":red_circle:"

        result += " " + name

        return result


    async def _print_status(self):
        """
            Print bot status
        """
        guild = self.get_guild(self.guild_id)

        state = "Obecny stan:\n"

        unknown_user_names = [guild.get_member(member_id).name for member_id in self.unknown_users]
        state += f"Nieznani użytkownicy: {len(unknown_user_names)}\n"
        state += f"Użytkownicy którzy zaakceptowali wszystkie części regulaminu: {len(self.member_ids_accepted_regulations)}\n"

        autorefresh = self.storage.get_config()[RolesBot.AutoRefreshEntry]
        time_left =  timedelta(minutes = autorefresh) - (datetime.now() - self.last_auto_refresh)
        state += f"Czas do automatycznego odświeżenia ról: {time_left}\n"
        state += f"Częstotliwość odświeżenia: {autorefresh} minut\n"

        autoroles_urls = [utils.generate_link(self.guild_id, id) for id in self.config.auto_roles_channels]
        autoroles_string = " ".join(autoroles_urls)
        state += f"Obserwowane kanały z autorolami: {autoroles_string}\n"

        autorefresh_string = utils.generate_link(self.guild_id, self.config.user_auto_refresh_roles_message_id)
        state += f"Wiadomość automatycznego odświeżenia użytkowników: {autorefresh_string}\n"

        regulations_urls = [utils.generate_link(self.guild_id, id) for id in self.config.server_regulations_message_ids]
        regulations_string = " ".join(regulations_urls)
        state += f"Wiadomości regulaminu do zaakceptowania: {regulations_string}\n"

        await self._write_to_dedicated_channel(state)


    async def _update_state(self):
        """
            Method collects and updates bot's information about server state.

            It is meant to be used on bot startup to get the lay of the land.
            It can also be used by a manual refresh if things get out of sync for any reason.
        """

        self.unknown_users = self._collect_unknown_users()
        self.member_ids_accepted_regulations = await self._collect_users_who_accepted_all_regulations()

        if self._is_level_sufficent_for_send(logging.DEBUG):
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


    async def _collect_users_who_accepted_all_regulations(self) -> Set[int]:
        """
            Collect users who accepted regulations
        """
        guild = self.get_guild(self.guild_id)

        accepted_messages = []

        for channel_id, message_id in self.config.server_regulations_message_ids:
            regulations_channel = guild.get_channel(channel_id)
            acceptance_message = await regulations_channel.fetch_message(message_id)

            members = set()

            for reaction in acceptance_message.reactions:
                emoji = reaction.emoji
                if str(emoji) == "👍":
                    members = {user.id async for user in reaction.users()}

            accepted_messages.append(members)

        members_who_accepted_all = set.intersection(*accepted_messages)

        return members_who_accepted_all
