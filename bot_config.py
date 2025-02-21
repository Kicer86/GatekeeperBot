
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from overrides import override

from .data_sources import RolesSource, NicknamesSource


class NullNicknamesSource(NicknamesSource):
    @override
    def get_nicknames_for(self, member_ids: List[int]) -> Dict[str, str]:
        return {str(id): None for id in member_ids}

    @override
    def get_all_nicknames(self) -> Dict[str, str]:
        return {}


@dataclass
class BotConfig:
    dedicated_channel: int                                                                  # channel id
    roles_source: RolesSource
    nicknames_source: NicknamesSource = NullNicknamesSource()
    auto_roles_channels: List[int] = field(default_factory=list)                            # channel ids
    server_regulations_message_ids: List[Tuple[int, int]] = field(default_factory=list)     # list of (channel id, message id)
    user_auto_refresh_roles_message_id: Tuple[int, int] = None                              # channel id, message id
    ids_channel_id: int = None                                                              # channel to put user ids
    guild_id: int = None                                                                    # allowed guild ID
    system_users: List[int] = field(default_factory=list)                                   # user ids to ignore during mass operations
