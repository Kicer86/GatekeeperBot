
import asyncio
import unittest

from unittest.mock import MagicMock

from ..event_processor import *


class TestRolesBot(unittest.IsolatedAsyncioTestCase):
    async def test_single_reaction_on_message(self):
        loop = asyncio.get_running_loop()

        actionMock = EventActions(
            on_reactionOnMessage = MagicMock(),
            on_unreactionOnMessage = MagicMock()
        )
        processor = EventProcessor(loop = loop, event_actions = actionMock)

        processor.add_event(type = EventType.ReactionOn, user_id = 123, data = ReactionOnMessage(message_id = 256))
        await processor.wait_for_idle()

        actionMock.on_reactionOnMessage.assert_called_once_with(123, ReactionOnMessage(message_id = 256))
        actionMock.on_unreactionOnMessage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
