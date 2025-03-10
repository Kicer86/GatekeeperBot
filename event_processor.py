
import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Union
from enum import Enum


class EventType(Enum):
    ReactionOn = 1
    UnreactionOn = 2


@dataclass
class ReactionOnMessage:
    message_id: int

    def __hash__(self):
        return hash(self.message_id)

    def __eq__(self, other):
        return self.message_id == other.message_id


@dataclass
class EventDetails:
    type: EventType
    data: Union[ReactionOnMessage]
    time: int


class EventProcessor:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.user_events = defaultdict(list)
        self.lock = asyncio.Lock()
        self.wakeup_event = asyncio.Event()
        self.auto_wakeup_task = None
        self.loop: asyncio.AbstractEventLoop = loop

        loop.create_task(self.process_events())


    def add_event(self, type: EventType, user_id: int, data: Union[ReactionOnMessage]):
        now = time.time()

        asyncio.create_task(self._safe_add_event(type, user_id, data, now))


    async def _safe_add_event(self, type: EventType, user_id: int, data: Union[ReactionOnMessage], time):
        async with self.lock:
            details = EventDetails(type = type, data = data, time = time)
            self.user_events[user_id].append(details)
            self.wakeup_event.set()


    async def process_events(self):
        while True:
            await self.wakeup_event.wait()
            self.wakeup_event.clear()

            if self.auto_wakeup_task is not None:
                # self.auto_wakeup_task.
                pass

            print(f"Waking up")

            async with self.lock:
                print(f"Event queue length: {len(self.user_events)}")

                for user, events in self.user_events.items():
                    events = self._optimize_events(events)

                    if len(events) == 0:
                        del self.user_events[user]
                    else:
                        self.user_events[user] = events

                if len(self.user_events) > 0:
                    self.auto_wakeup_task = self.loop.create_task(self._auto_wakup())


    async def _auto_wakup(self):
        await asyncio.sleep(0.5)
        self.wakeup_event.set()
        print("Auto wakeup")


    def _optimize_events(self, events: List[EventDetails]):
        new_events = []

        message_reactions = defaultdict(int)
        last_reaction_time = defaultdict(int)

        for event in events:
            if event.type == EventType.ReactionOn:
                assert isinstance(event.data, ReactionOnMessage)
                message_reactions[event.data] += 1
                last_reaction_time[event.data] = max(last_reaction_time[event.data], event.time)
            elif event.type == EventType.UnreactionOn:
                assert isinstance(event.data, ReactionOnMessage)
                message_reactions[event.data] -= 1
                last_reaction_time[event.data] = max(last_reaction_time[event.data], event.time)
            else:
                new_events.append(event)

        # process total result or react / unreact acions
        for reaction_data, count in message_reactions.items():
            assert count == -1 or count == 0 or count == 1

            if count == -1:
                new_events.append(EventDetails(type == EventType.UnreactionOn, data = reaction_data, time = last_reaction_time[reaction_data]))
            elif count == 1:
                new_events.append(EventDetails(type == EventType.ReactionOn, data = reaction_data, time = last_reaction_time[reaction_data]))

        return new_events
