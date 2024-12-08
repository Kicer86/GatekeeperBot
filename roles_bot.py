
import discord

from typing import Dict, List, Tuple


class RolesSource:
    def get_expected_roles(self) -> Dict[str, Tuple[List[str], List[str]]]:   # user name, (roles to be added, roles to be removed)
        pass


class RolesBot(discord.Client):
    def __init__(self, roles_source: RolesSource):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents = intents)
        self.roles_source = roles_source

    async def on_ready(self):
        print(f"Bot is ready as {self.user}")

    async def on_message(self, message):
        if self.user in message.mentions and len(message.mentions) == 1:
            if not any(role.name == "Administrator" for role in message.author.roles):
                await message.channel.send("Tylko administrator może wydawać polecenia.")
                return

            print(message.content)

            if message.content == f"<@{self.user.id}> refresh":
                async with message.channel.typing():
                    await self._refresh_roles(message.guild.members, message.channel)

    async def _refresh_roles(self, members, channel):
        expected_roles = self.roles_source.get_expected_roles()

        no_data_for = []
        added_roles = {}
        removed_roles = {}

        for member in members:
            id = str(member.id)
            username = member.name
            roles = member.roles

            def apply_roles(to_add, to_remove):
                added_roles[member.name] = to_add
                removed_roles[member.name] = to_remove

            if username in expected_roles:
                apply_roles(*expected_roles[username])
            elif id in expected_roles:
                apply_roles(*expected_roles[id])
            else:
                no_data_for.append(member.name)

        if len(added_roles) > 0:
            added_roles_status = "Nowe role nadane użytkownikom:\n"
            for user, roles in added_roles.items():
                added_roles_status += f"{user}: {", ".join(roles)}\n"

            await channel.send(added_roles_status)

        if len(removed_roles) > 0:
            removed_roles_status = "Role zabrane użytkownikom:\n"
            for user, roles in removed_roles.items():
                removed_roles_status += f"{user}: {", ".join(roles)}\n"

            await channel.send(removed_roles_status)

        if len(no_data_for) > 0:
            no_data_for_status = "Użytkownicy obecni na serwerze, dla których brak danych w baze danych:\n"
            no_data_for_status += ", ".join(no_data_for)

            await channel.send(no_data_for_status)
