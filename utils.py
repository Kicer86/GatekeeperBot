
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


async def build_user_name(client: discord.Client, guild: discord.Guild, id: int) -> (str, str):
    """
        Function return string with user name in a uniformed way.
        All special characters are being escaped.

        Two strings are returned: first is for discord message, second for logging
    """
    member = guild.get_member(id)

    if member is None:
        try:
            member = await client.fetch_user(id)
        except discord.NotFound:
            pass

    for_discord = escape_markdown(f"{id}" if member is None else f"{member.display_name} ({member.name})")
    for_logs = repr(f"{id}" if member is None else f"({id} {member.name} {member.display_name})")

    return (for_discord, for_logs)


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


async def remove_user_reactions(guild: discord.Guild, message: discord.Message, member_id: int) -> bool:
    try:
        for reaction in message.reactions:
            async for user in reaction.users():
                if user.id == member_id:
                    await reaction.remove(user)
    except discord.Forbidden:
        return False
    except discord.HTTPException as e:
        return False

    return True


def generate_link(guild_id: int, items):
    leaf = "/".join(map(str, items)) if isinstance(items, tuple) else items
    url = f"https://discord.com/channels/{guild_id}/{leaf}"

    return url


async def get_message(guild: discord.Guild, channel_id: int, message_id: int) -> discord.Message:
    channel: discord.TextChannel = guild.get_channel(channel_id)
    message: discord.Message = await channel.fetch_message(message_id)

    return message
