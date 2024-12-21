
import discord
import logging
import unittest
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

from roles_bot import RolesBot, RolesSource

class DiscordMock:
    def __init__(self):
        self.guild = MagicMock(spec=discord.Guild)
        self.channels = {}
        self.roles = {}
        self.global_id_counter = 1

    def get_next_id(self):
        next_id = self.global_id_counter
        self.global_id_counter += 1
        return next_id

    def create_role(self, name: str):
        role_id = self.get_next_id()
        role = discord.Role(guild=self.guild, state=None, data={"id": role_id, "name": name})
        self.roles[name] = role
        return role

    def setup_guild_roles(self, role_names):
        self.guild.roles = [self.create_role(name) for name in role_names]

    def setup_member(self, name: str, initial_roles):
        member_id = self.get_next_id()
        member = MagicMock(spec=discord.Member)
        member.guild = self.guild
        member.name = name
        member.id = member_id
        member.roles = [self.roles[role_name] for role_name in initial_roles]
        member.remove_roles = AsyncMock()
        member.add_roles = AsyncMock()
        return member

    def add_channel(self, name: str):
        channel_id = self.get_next_id()
        channel = AsyncMock(spec=discord.TextChannel)
        channel.id = channel_id
        channel.name = name
        self.channels[channel_id] = channel
        return channel_id

    async def mock_fetch_channel(self, bot_self, channel_id: int) -> discord.abc.GuildChannel:
        return self.channels.get(channel_id, None)


class TestRolesBot(unittest.IsolatedAsyncioTestCase):
    async def test_user_joins(self):
        discordMock = DiscordMock()
        discordMock.setup_guild_roles(["Add1", "Add2", "RemoveMe", "RemoveMeToo", "LeaveMe"])
        report_channel_id = discordMock.add_channel("report_channel")
        member = discordMock.setup_member("TestUser", ["RemoveMe", "RemoveMeToo", "LeaveMe"])

        roles_source = MagicMock(spec=RolesSource())
        def fetch_user_roles(member):
            return ("Add1", "Add2"), ("RemoveMe", "RemoveMeToo")
        roles_source.fetch_user_roles.side_effect = fetch_user_roles

        bot = RolesBot(dedicated_channel=report_channel_id, roles_source=roles_source, auto_roles_channels=[], logger=logging.getLogger("Test"))
        bot.fetch_channel = partial(discordMock.mock_fetch_channel, discordMock)

        with patch.object(RolesBot, "guilds", new=[discordMock.guild]):
            # Emulate member join
            await bot.on_ready()
            await bot.on_member_join(member)

            # Assert the bot sent a message to the report channel
            discordMock.channels[report_channel_id].send.assert_called_once_with(
                "Aktualizacja ról nowego użytkownika TestUser zakończona.\nNadane role:\nAdd1, Add2\nUsunięte role:\nRemoveMe, RemoveMeToo"
            )

            # Assert roles were correctly removed
            member.remove_roles.assert_awaited_once_with(
                *[role for role in discordMock.guild.roles if role.name in ["RemoveMe", "RemoveMeToo"]]
            )

            # Assert roles were correctly added
            member.add_roles.assert_awaited_once_with(
                *[role for role in discordMock.guild.roles if role.name in ["Add1", "Add2"]]
            )

if __name__ == "__main__":
    unittest.main()
