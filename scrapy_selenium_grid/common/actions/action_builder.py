from typing import Awaitable
#-
from selenium.webdriver.common.actions.action_builder import (
        ActionBuilder as BaseActionBuilder,)
from selenium.webdriver.remote.command import Command

class ActionBuilder(BaseActionBuilder):

    async def perform(self) -> Awaitable[None]:
        enc = {"actions": []}
        for device in self.devices:
            encoded = device.encode()
            if encoded["actions"]:
                enc["actions"].append(encoded)
                device.actions = []
        await self.driver.execute(Command.W3C_ACTIONS, enc)


    async def clear_actions(self) -> Awaitable[None]:
        """Clears actions that are already stored on the remote end."""
        await self.driver.execute(Command.W3C_CLEAR_ACTIONS)
