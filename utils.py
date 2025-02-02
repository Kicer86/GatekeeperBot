
import discord

from discord.utils import escape_markdown
from typing import Union


async def build_user_name_for_discord_message(client: discord.Client, guild: discord.Guild, id: int) -> str:
    """
        Function return string with user name in a uniformed way.
        All special characters are being escaped
    """
    member = guild.get_member(id)

    if member is None:
        try:
            member = await client.fetch_user(id)
        except discord.NotFound:
            pass

    result = escape_markdown(f"{id}" if member is None else f"{member.display_name} ({member.name})")

    return result


async def build_user_name_for_log(client: discord.Client, guild: discord.Guild, id: int) -> str:
    """
        Function return string with user name in a uniformed way.
        All special characters are being escaped
    """
    member = guild.get_member(id)

    if member is None:
        try:
            member = await client.fetch_user(id)
        except discord.NotFound:
            pass

    result = f"{id}" if member is None else repr(f"({id} {member.name} {member.display_name})")

    return result


async def get_user_status(client: discord.Client, guild: discord.Guild, id: int) -> Union[bool, None]:
    """
        function return True if user exists and is available on the guild
                        False if user exists and is not available on the guild
                        None is user does not exists
    """

    if guild.get_member(id) is None:
        try:
            await client.fetch_user(id)
            return False
        except discord.NotFound:
            return None
    else:
        return True
