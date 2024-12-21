
import discord
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from roles_bot import RolesBot, RolesSource


class TestMyBotCommands(unittest.IsolatedAsyncioTestCase):
    async def test_user_joins(self):
        guild = MagicMock(spec=discord.Guild)

        def fetch_user_roles(member):
            return ("Add1", "Add2"), ("RemoveMe", "RemoveMeToo")

        async def fetch_channel(self, channel_id: int) -> discord.abc.GuildChannel:
            if channel_id == 1:
                return report_channel
            else:
                return None

        def create_role(name: str, id: int):
            role = discord.Role(guild=guild, state=None, data={"id": id, "name": name})
            return role

        roles_source = MagicMock(spec=RolesSource())
        bot = RolesBot(dedicated_channel=1, roles_source=roles_source, auto_roles_channels=[2, 3, 4], logger=logging.getLogger("Test"))

        guild.roles = [create_role(name, i + 100) for i, name in enumerate(["Add1", "Add2", "RemoveMe", "RemoveMeToo", "LeaveMe"])]

        member = MagicMock(spec=discord.Member)
        member.guild = guild
        member.name = "TestUser"
        member.id = 1234567890
        member.roles = [role for role in guild.roles if role.name in ["RemoveMe", "RemoveMeToo", "LeaveMe"]]

        roles_source.fetch_user_roles.side_effect = fetch_user_roles

        report_channel = AsyncMock(spec=discord.TextChannel)

        bot.fetch_channel = fetch_channel.__get__(bot)

        member.remove_roles = AsyncMock()
        member.add_roles = AsyncMock()

        with patch.object(RolesBot, "guilds", new=[guild]):
            # Emulate member join
            await bot.on_ready()
            await bot.on_member_join(member)

            # Assert the bot sent a message to the welcome channel
            report_channel.send.assert_called_once_with(
                "Aktualizacja ról nowego użytkownika TestUser zakończona.\nNadane role:\nAdd1, Add2\nUsunięte role:\nRemoveMe, RemoveMeToo"
            )

            # Assert roles were correctly removed
            member.remove_roles.assert_awaited_once_with(
                *[role for role in guild.roles if role.name in ["RemoveMe", "RemoveMeToo"]]
            )

            # Assert roles were correctly added
            member.add_roles.assert_awaited_once_with(
                *[role for role in guild.roles if role.name in ["Add1", "Add2"]]
            )

if __name__ == "__main__":
    unittest.main()
