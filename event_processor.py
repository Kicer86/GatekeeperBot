
import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Dict, List, Union
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


@dataclass
class EventActions:
    on_reactionOnMessage: Callable[[int, any], None]
    on_unreactionOnMessage : Callable[[int, any], None]


class EventProcessor:
    def __init__(self, loop: asyncio.AbstractEventLoop, event_actions: EventActions, treshhold: float = 1.0):
        self.user_events = defaultdict(list)
        self.lock = asyncio.Lock()
        self.wakeup_event = asyncio.Event()
        self.auto_wakeup_task = None
        self.loop: asyncio.AbstractEventLoop = loop
        self.treshhold = treshhold
        self.event_actions = event_actions

        loop.create_task(self.process_events())


    async def get_users_events(self) -> Dict[int, List[EventDetails]]:
         async with self.lock:
             return self.user_events


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

                # optimize events
                for user_id, events in self.user_events.items():
                    events = self._optimize_events(events)

                    self.user_events[user_id] = events

                # drop empty lists of events
                self.user_events = {user_id: events for user_id, events in self.user_events.items() if len(events) > 0}

                # sort events
                for user_id, events in self.user_events.items():
                    events = self._optimize_events(events)
                    events.sort(key = lambda event: event.time)
                    self.user_events[user_id] = events

                # execute events by time
                now = time.time()
                for user_id, events in self.user_events.items():
                    new_events = []
                    for event in events:
                        if now - event.time > self.treshhold:
                            if event.type == EventType.ReactionOn:
                                self.event_actions.on_reactionOnMessage(user_id, event.data)
                            elif event.type == EventType.UnreactionOn:
                                self.event_actions.on_unreactionOnMessage(user_id, event.data)
                            else:
                                assert False
                        else:
                            new_events.append(event)

                    self.user_events[user_id] = new_events

                # suspend or hibernate
                users_to_process = len(self.user_events)
                if users_to_process > 0:
                    print(f"{users_to_process} left with unprocessed events. Checking on them soon")
                    self.auto_wakeup_task = self.loop.create_task(self._auto_wakup())
                else:
                    print("No events left, entering hibernation state")


    async def _auto_wakup(self):
        await asyncio.sleep(0.5)
        self.wakeup_event.set()
        print("Auto wakeup")


    def _optimize_events(self, events: List[EventDetails]):
        new_events = []

        message_reactions = defaultdict(int)
        last_reaction_time = defaultdict(int)

        # collect sum of reactions / unreaction for single message
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

        # collapse all reactions for the same message into one (or zero) events
        for reaction_data, count in message_reactions.items():
            assert count == -1 or count == 0 or count == 1

            if count == -1:
                new_events.append(EventDetails(type = EventType.UnreactionOn, data = reaction_data, time = last_reaction_time[reaction_data]))
            elif count == 1:
                new_events.append(EventDetails(type = EventType.ReactionOn, data = reaction_data, time = last_reaction_time[reaction_data]))

        return new_events
