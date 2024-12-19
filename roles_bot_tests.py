
import discord
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from roles_bot import RolesBot, RolesSource


class TestMyBotCommands(unittest.IsolatedAsyncioTestCase):
    async def test_user_joins(self):
        roles_source = MagicMock(spec = RolesSource())
        bot = RolesBot(dedicated_channel = 1, roles_source = roles_source, auto_roles_channels = [2, 3, 4], logger = logging.getLogger("Test"))

        guild = MagicMock(spec=discord.Guild)
        guild.roles = []

        member = MagicMock(spec=discord.Member)
        member.guild = guild
        member.name = "TestUser"
        member.id = 1234567890

        def fetch_user_roles(member):
            return (["Add1", "Add2"], ["RemoveMe", "RemoveMeToo"])

        roles_source.fetch_user_roles.side_effect = fetch_user_roles

        report_channel = AsyncMock(spec=discord.TextChannel)

        async def fetch_channel(self, channel_id: int) -> discord.abc.GuildChannel:
            if channel_id == 1:
                return report_channel
            else:
                return None

        bot.fetch_channel = fetch_channel.__get__(bot)

        with patch.object(RolesBot, "guilds", new=[guild]):
            # emulate member join
            await bot.on_ready()
            await bot.on_member_join(member)

            # Assert the bot sent a message to the welcome channel
            report_channel.send.assert_called_once_with(
                "Aktualizacja ról nowego użytkownika TestUser zakończona.\nNadane role:\nTestUser\n"
            )

if __name__ == "__main__":
    unittest.main()
