
import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Union
from enum import Enum


class EventType(Enum):
    ReactionOnAutoRole = 1
    UnreactionOnAutoRole = 2


@dataclass
class ReactionOnMessage:
    message_id: int


class EventProcessor:
    def __init__(self):
        self.user_events = defaultdict(list)
        self.lock = asyncio.Lock()
        self.wakeup_event = asyncio.Event()

        loop = asyncio.get_event_loop()
        loop.create_task(self.process_events())


    def add_event(self, type: EventType, user_id: int, data: Union[ReactionOnMessage]):
        now = time.time()

        asyncio.create_task(self._safe_add_event(type, user_id, data, now))


    async def _safe_add_event(self, type: EventType, user_id: int, data: Union[ReactionOnMessage], time):
        async with self.lock:
            self.user_events[user_id].append(type, data, time)
            self.wakeup_event.set()


    async def process_events(self):
        while True:
            await self.wakeup_event.wait()
            self.wakeup_event.clear()

            async with self.lock:
                print(f"Event queue length: {len(self.user_events)}")

                self.user_events.popitem()
