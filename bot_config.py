
from dataclasses import dataclass
from typing import List, Tuple

from .data_sources import RolesSource, NicknamesSource

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
    system_users: List[int]                                 # user ids to ignore during mass operations
