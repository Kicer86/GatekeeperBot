
import discord

from typing import Dict, List, Tuple


class RolesSource:
    def get_expected_roles(self) -> Dict[str, Tuple[List[str], List[str]]]:   # user name, (roles to be added, roles to be removed)
        pass


class RolesBot(discord.Client):
    def __init__(self, dedicated_channel: str, roles_source: RolesSource):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents = intents)
        self.roles_source = roles_source
        self.channel_name = dedicated_channel
        self.channel = None

    async def on_ready(self):
        print(f"Bot is ready as {self.user}")

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
        await self.channel.send(message)

    async def _refresh_roles(self, members):
        expected_roles = self.roles_source.get_expected_roles()

        no_data_for = []
        added_roles = {}
        removed_roles = {}

        for member in members:
            id = str(member.id)
            username = member.name
            roles = member.roles
            role_names = {role.name for role in roles}

            async def apply_roles(to_add, to_remove):
                # add missing roles
                missing = [add for add in to_add if add not in role_names]

                if len(missing) > 0:
                    missing_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in missing]
                    await member.add_roles(*missing_ids)
                    added_roles[member.name] = missing

                # remove taken roles
                redundant = [remove for remove in to_remove if remove in role_names]

                if len(redundant) > 0:
                    redundant_ids = [discord.utils.get(member.guild.roles, name=role_name) for role_name in redundant]
                    await member.remove_roles(*redundant_ids)
                    removed_roles[member.name] = redundant

            if username in expected_roles:
                await apply_roles(*expected_roles[username])
            elif id in expected_roles:
                await apply_roles(*expected_roles[id])
            else:
                no_data_for.append(member.name)

        if len(added_roles) > 0:
            added_roles_status = "Nowe role nadane użytkownikom:\n"
            for user, roles in added_roles.items():
                added_roles_status += f"{user}: {", ".join(roles)}\n"

            await self._write_to_dedicated_channel(added_roles_status)

        if len(removed_roles) > 0:
            removed_roles_status = "Role zabrane użytkownikom:\n"
            for user, roles in removed_roles.items():
                removed_roles_status += f"{user}: {", ".join(roles)}\n"

            await self._write_to_dedicated_channel(removed_roles_status)

        if len(no_data_for) > 0:
            no_data_for_status = "Użytkownicy obecni na serwerze, dla których brak danych w bazie danych:\n"
            no_data_for_status += ", ".join(no_data_for)

            await self._write_to_dedicated_channel(no_data_for_status)
