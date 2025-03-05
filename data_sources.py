
import discord
from typing import Any, Dict, List, Tuple, Union
from enum import Enum


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
    def get_nicknames_for(self, member_ids: List[int]) -> Dict[str, Union[str, None]]:
        pass

    def get_all_nicknames(self) -> Dict[str, str]:
        pass
