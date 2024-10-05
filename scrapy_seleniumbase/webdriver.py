# Licensed to the Software Freedom Conservancy (SFC) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The SFC licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""The WebDriver implementation."""
from base64 import b64decode
from base64 import urlsafe_b64encode
from contextlib import asynccontextmanager
from contextlib import contextmanager
from contextlib import suppress
import os
import pkgutil
import types
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Optional
from typing import Type
from typing import Union
import warnings
import zipfile
#-
from selenium.common.exceptions import InvalidArgumentException
from selenium.common.exceptions import JavascriptException
from selenium.common.exceptions import NoSuchCookieException
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.options import BaseOptions
from selenium.webdriver.common.print_page_options import PrintOptions
from selenium.webdriver.common.timeouts import Timeouts
from selenium.webdriver.common.virtual_authenticator import Credential
from selenium.webdriver.common.virtual_authenticator import (
        VirtualAuthenticatorOptions,)
from selenium.webdriver.common.virtual_authenticator import (
        required_virtual_authenticator,)
from selenium.webdriver.remote import webdriver
from selenium.webdriver.remote.bidi_connection import BidiConnection
from selenium.webdriver.remote.command import Command
from selenium.webdriver.remote.errorhandler import ErrorHandler
from selenium.webdriver.remote.file_detector import FileDetector
from selenium.webdriver.remote.file_detector import LocalFileDetector
from selenium.webdriver.remote.script_key import ScriptKey
from selenium.webdriver.support.relative_locator import RelativeBy
#-
from .mobile import Mobile
from .remote_connection.base import RemoteConnection
from .shadowroot import ShadowRoot
from .switch_to import SwitchTo
from .webelement import WebElement

def get_remote_connection(capabilities, command_executor, keep_alive,
        ignore_local_proxy=False):
    from .remote_connection.chrome import ChromeRemoteConnection
    from .remote_connection.edge import EdgeRemoteConnection
    from .remote_connection.firefox import FirefoxRemoteConnection
    from .remote_connection.safari import SafariRemoteConnection

    candidates = [ChromeRemoteConnection, EdgeRemoteConnection,
            SafariRemoteConnection, FirefoxRemoteConnection]
    handler = next((c for c in candidates \
            if c.browser_name == capabilities.get("browserName")), RemoteConnection)

    return handler(command_executor, keep_alive=keep_alive,
            ignore_proxy=ignore_local_proxy)


class WebDriver(webdriver.BaseWebDriver):
    """Controls a browser by sending commands to a remote server. This server
    is expected to be running the WebDriver wire protocol as defined at
    https://www.selenium.dev/documentation/legacy/json_wire_protocol/.

    :Attributes:
     - session_id - String ID of the browser session started and controlled by this
         WebDriver.
     - capabilities - Dictionary of effective capabilities of this browser session
         as returned by the remote server.
         See https://www.selenium.dev/documentation/legacy/desired_capabilities/
     - command_executor - remote_connection.RemoteConnection object used to execute
         commands.
     - error_handler - errorhandler.ErrorHandler object used to handle errors.
    """

    _web_element_cls = WebElement
    _shadowroot_cls = ShadowRoot

    def __init__(self, command_executor: RemoteConnection,
            file_detector: Optional[FileDetector] = None) \
            -> None:
        """Create a new driver that will issue commands using the wire
        protocol.

        :Args:
         - command_executor - custom remote_connection.RemoteConnection object.
         - file_detector - Pass custom file detector object during instantiation.
             If None, then default LocalFileDetector() will be used.
        """

        self.command_executor = command_executor
        self._is_remote = True
        self.session_id = None
        self.caps = {}
        self.pinned_scripts = {}
        self.error_handler = ErrorHandler()
        self._switch_to = SwitchTo(self)
        self._mobile = Mobile(self)
        self.file_detector = file_detector or LocalFileDetector()
        self._authenticator_id = None


    @classmethod
    async def create(
            cls,
            command_executor: Union[str, RemoteConnection] \
                = 'http://127.0.0.1:4444',
            keep_alive: bool = True,
            file_detector: Optional[FileDetector] = None,
            options: Optional[Union[BaseOptions, List[BaseOptions]]] = None) \
            -> None:
        """Create a new driver that will issue commands using the wire
        protocol.

        :Args:
         - command_executor - Either a string representing URL of the remote server
             or a custom remote_connection.RemoteConnection object.
             Defaults to 'http://127.0.0.1:4444/wd/hub'.
         - keep_alive - Whether to configure remote_connection.RemoteConnection to
             use HTTP keep-alive. Defaults to True.
         - file_detector - Pass custom file detector object during instantiation.
             If None, then default LocalFileDetector() will be used.
         - options - instance of a driver options.Options class
        """

        if isinstance(options, list):
            capabilities = webdriver.create_matches(options)
            _ignore_local_proxy = False
        else:
            capabilities = options.to_capabilities()
            _ignore_local_proxy = options._ignore_local_proxy
        if isinstance(command_executor, (str, bytes)):
            command_executor = get_remote_connection(
                    capabilities,
                    command_executor=command_executor,
                    keep_alive=keep_alive,
                    ignore_local_proxy=_ignore_local_proxy)
        obj = cls(command_executor=command_executor, file_detector=file_detector)
        await obj.start_session(capabilities)
        return obj


    def __repr__(self):
        return (
            f'<{type(self).__module__}.{type(self).__name__} '
            f'(session="{self.session_id}")>'
        )


    async def __aenter__(self):
        return self


    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
            exc: Optional[BaseException],
            traceback: Optional[types.TracebackType]):
        await self.quit()


    @contextmanager
    def file_detector_context(self, file_detector_class, *args, **kwargs):
        """Overrides the current file detector (if necessary) in limited
        context. Ensures the original file detector is set afterwards.

        Example::

            with webdriver.file_detector_context(UselessFileDetector):
                someinput.send_keys('/etc/hosts')

        :Args:
         - file_detector_class - Class of the desired file detector. If the class
             is different from the current file_detector, then the class is
             instantiated with args and kwargs and used as a file detector during
             the duration of the context manager.
         - args - Optional arguments that get passed to the file detector class
             during instantiation.
         - kwargs - Keyword arguments, passed the same way as args.
        """
        last_detector = None
        if not isinstance(self.file_detector, file_detector_class):
            last_detector = self.file_detector
            self.file_detector = file_detector_class(*args, **kwargs)
        try:
            yield
        finally:
            if last_detector:
                self.file_detector = last_detector


    @property
    def mobile(self) -> Mobile:
        return self._mobile


    @property
    def name(self) -> str:
        """Returns the name of the underlying browser for this instance.

        :Usage:
            ::

                name = driver.name
        """
        if "browserName" in self.caps:
            return self.caps["browserName"]
        raise KeyError("browserName not specified in session capabilities")


    async def start_session(self, capabilities: dict) -> None:
        """Creates a new session with the desired capabilities.

        :Args:
         - capabilities - a capabilities dict to start the session with.
        """

        caps = webdriver._create_caps(capabilities)
        response = (await self.execute(Command.NEW_SESSION, caps))["value"]
        self.session_id = response.get("sessionId")
        self.caps = response.get("capabilities")


    def _wrap_value(self, value):
        if isinstance(value, dict):
            converted = {}
            for key, val in value.items():
                converted[key] = self._wrap_value(val)
            return converted
        if isinstance(value, self._web_element_cls):
            return {"element-6066-11e4-a52e-4f735466cecf": value.id}
        if isinstance(value, self._shadowroot_cls):
            return {"shadow-6066-11e4-a52e-4f735466cecf": value.id}
        if isinstance(value, list):
            return list(self._wrap_value(item) for item in value)
        return value


    def create_web_element(self, element_id: str) -> WebElement:
        """Creates a web element with the specified `element_id`."""
        return self._web_element_cls(self, element_id)


    def _unwrap_value(self, value):
        if isinstance(value, dict):
            if "element-6066-11e4-a52e-4f735466cecf" in value:
                return self.create_web_element(
                        value["element-6066-11e4-a52e-4f735466cecf"])
            if "shadow-6066-11e4-a52e-4f735466cecf" in value:
                return self._shadowroot_cls(self,
                        value["shadow-6066-11e4-a52e-4f735466cecf"])
            for key, val in value.items():
                value[key] = self._unwrap_value(val)
            return value
        if isinstance(value, list):
            return list(self._unwrap_value(item) for item in value)
        return value


    async def execute(self, driver_command: str, params: dict = None) \
            -> Awaitable[dict]:
        """Sends a command to be executed by a command.CommandExecutor.

        :Args:
         - driver_command: The name of the command to execute as a string.
         - params: A dictionary of named parameters to send with the command.

        :Returns:
          The command's JSON response loaded into a dictionary object.
        """
        params = self._wrap_value(params)

        if self.session_id:
            if not params:
                params = {"sessionId": self.session_id}
            elif "sessionId" not in params:
                params["sessionId"] = self.session_id

        response = await self.command_executor.execute(driver_command, params)
        if response:
            self.error_handler.check_response(response)
            response["value"] = self._unwrap_value(response.get("value", None))
            return response
        # If the server doesn't send a response, assume the command was
        # a success
        return {"success": 0, "value": None, "sessionId": self.session_id}


    async def get(self, url: str) -> None:
        """Loads a web page in the current browser session."""
        await self.execute(Command.GET, {"url": url})


    @property
    async def title(self) -> str:
        """Returns the title of the current page.

        :Usage:
            ::

                title = driver.title
        """
        return (await self.execute(Command.GET_TITLE)).get("value", "")


    def pin_script(self, script: str, script_key=None) -> ScriptKey:
        """Store common javascript scripts to be executed later by a unique
        hashable ID."""
        script_key_instance = ScriptKey(script_key)
        self.pinned_scripts[script_key_instance.id] = script
        return script_key_instance


    def unpin(self, script_key: ScriptKey) -> None:
        """Remove a pinned script from storage."""
        try:
            self.pinned_scripts.pop(script_key.id)
        except KeyError:
            raise KeyError(
                f"No script with key: {script_key} existed in "
                f"{self.pinned_scripts}"
            ) from None


    def get_pinned_scripts(self) -> List[str]:
        return list(self.pinned_scripts)


    async def execute_script(self, script, *args):
        """Synchronously Executes JavaScript in the current window/frame.

        :Args:
         - script: The JavaScript to execute.
         - \\*args: Any applicable arguments for your JavaScript.

        :Usage:
            ::

                driver.execute_script('return document.title;')
        """
        if isinstance(script, ScriptKey):
            try:
                script = self.pinned_scripts[script.id]
            except KeyError:
                raise JavascriptException("Pinned script could not be found")

        converted_args = list(args)
        command = Command.W3C_EXECUTE_SCRIPT

        return (await self.execute(command,
                {"script": script, "args": converted_args})) \
                ["value"]


    async def execute_async_script(self, script: str, *args):
        """Asynchronously Executes JavaScript in the current window/frame.

        :Args:
         - script: The JavaScript to execute.
         - \\*args: Any applicable arguments for your JavaScript.

        :Usage:
            ::

                script = "var callback = arguments[arguments.length - 1]; " \\
                         "window.setTimeout(function(){ callback('timeout') }, 3000);"
                driver.execute_async_script(script)
        """
        converted_args = list(args)
        command = Command.W3C_EXECUTE_SCRIPT_ASYNC

        return (await self.execute(command,
                {"script": script, "args": converted_args})) \
                ["value"]


    @property
    async def current_url(self) -> Awaitable[str]:
        """Gets the URL of the current page.

        :Usage:
            ::

                driver.current_url
        """
        return (await self.execute(Command.GET_CURRENT_URL))["value"]


    @property
    async def page_source(self) -> Awaitable[str]:
        """Gets the source of the current page.

        :Usage:
            ::

                driver.page_source
        """
        return (await self.execute(Command.GET_PAGE_SOURCE))["value"]


    @property
    def closed(self):
        return self.command_executor.closed


    async def close(self) -> Awaitable[None]:
        """Closes the current window.

        :Usage:
            ::

                driver.close()
        """
        await self.execute(Command.CLOSE)


    async def quit(self) -> Awaitable[None]:
        """Quits the driver and closes every associated window.

        :Usage:
            ::

                driver.quit()
        """
        try:
            await self.execute(Command.QUIT)
        finally:
            await self.command_executor.close()


    @property
    async def current_window_handle(self) -> Awaitable[str]:
        """Returns the handle of the current window.

        :Usage:
            ::

                driver.current_window_handle
        """
        return (await self.execute(Command.W3C_GET_CURRENT_WINDOW_HANDLE))["value"]


    @property
    async def window_handles(self) -> Awaitable[List[str]]:
        """Returns the handles of all windows within the current session.

        :Usage:
            ::

                driver.window_handles
        """
        return (await self.execute(Command.W3C_GET_WINDOW_HANDLES))["value"]


    async def maximize_window(self) -> Awaitable[None]:
        """Maximizes the current window that webdriver is using."""
        command = Command.W3C_MAXIMIZE_WINDOW
        await self.execute(command, None)


    async def fullscreen_window(self) -> Awaitable[None]:
        """Invokes the window manager-specific 'full screen' operation."""
        await self.execute(Command.FULLSCREEN_WINDOW)


    async def minimize_window(self) -> Awaitable[None]:
        """Invokes the window manager-specific 'minimize' operation."""
        await self.execute(Command.MINIMIZE_WINDOW)


    async def print_page(self, print_options: Optional[PrintOptions] = None) \
            -> Awaitable[str]:
        """Takes PDF of the current page.

        The driver makes a best effort to return a PDF based on the
        provided parameters.
        """
        options = {}
        if print_options:
            options = print_options.to_dict()

        return (await self.execute(Command.PRINT_PAGE, options))["value"]


    @property
    def switch_to(self) -> SwitchTo:
        """
        :Returns:
            - SwitchTo: an object containing all options to switch focus into

        :Usage:
            ::

                element = driver.switch_to.active_element
                alert = driver.switch_to.alert
                driver.switch_to.default_content()
                driver.switch_to.frame('frame_name')
                driver.switch_to.frame(1)
                driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[0])
                driver.switch_to.parent_frame()
                driver.switch_to.window('main')
        """
        return self._switch_to


    # Navigation
    async def back(self) -> Awaitable[None]:
        """Goes one step backward in the browser history.

        :Usage:
            ::

                driver.back()
        """
        await self.execute(Command.GO_BACK)


    async def forward(self) -> Awaitable[None]:
        """Goes one step forward in the browser history.

        :Usage:
            ::

                driver.forward()
        """
        await self.execute(Command.GO_FORWARD)


    async def refresh(self) -> Awaitable[None]:
        """Refreshes the current page.

        :Usage:
            ::

                driver.refresh()
        """
        await self.execute(Command.REFRESH)


    # Options
    async def get_cookies(self) -> Awaitable[List[dict]]:
        """Returns a set of dictionaries, corresponding to cookies visible in
        the current session.

        :Usage:
            ::

                driver.get_cookies()
        """
        return (await self.execute(Command.GET_ALL_COOKIES))["value"]


    async def get_cookie(self, name) -> Awaitable[Optional[Dict]]:
        """Get a single cookie by name. Returns the cookie if found, None if
        not.

        :Usage:
            ::

                driver.get_cookie('my_cookie')
        """
        with suppress(NoSuchCookieException):
            return (await self.execute(Command.GET_COOKIE, {"name": name}))["value"]
        return None


    async def delete_cookie(self, name) -> Awaitable[None]:
        """Deletes a single cookie with the given name.

        :Usage:
            ::

                driver.delete_cookie('my_cookie')
        """
        await self.execute(Command.DELETE_COOKIE, {"name": name})


    async def delete_all_cookies(self) -> Awaitable[None]:
        """Delete all cookies in the scope of the session.

        :Usage:
            ::

                driver.delete_all_cookies()
        """
        await self.execute(Command.DELETE_ALL_COOKIES)


    async def add_cookie(self, cookie_dict) -> Awaitable[None]:
        """Adds a cookie to your current session.

        :Args:
         - cookie_dict: A dictionary object, with
            required keys - "name" and "value";
            optional keys - "path", "domain", "secure", "httpOnly", "expiry",
                "sameSite"

        :Usage:
            ::

                driver.add_cookie({'name' : 'foo', 'value' : 'bar'})
                driver.add_cookie({'name' : 'foo', 'value' : 'bar', 'path' : '/'})
                driver.add_cookie({'name' : 'foo', 'value' : 'bar', 'path' : '/',
                                   'secure' : True})
                driver.add_cookie({'name' : 'foo', 'value' : 'bar',
                                   'sameSite' : 'Strict'})
        """
        if "sameSite" in cookie_dict:
            assert cookie_dict["sameSite"] in ["Strict", "Lax", "None"]
            await self.execute(Command.ADD_COOKIE, {"cookie": cookie_dict})
        else:
            await self.execute(Command.ADD_COOKIE, {"cookie": cookie_dict})


    # Timeouts
    async def implicitly_wait(self, time_to_wait: float) -> Awaitable[None]:
        """Sets a sticky timeout to implicitly wait for an element to be found,
        or a command to complete. This method only needs to be called one time
        per session. To set the timeout for calls to execute_async_script, see
        set_script_timeout.

        :Args:
         - time_to_wait: Amount of time to wait (in seconds)

        :Usage:
            ::

                driver.implicitly_wait(30)
        """
        await self.execute(Command.SET_TIMEOUTS,
                {"implicit": int(float(time_to_wait) * 1000)})


    async def set_script_timeout(self, time_to_wait: float) -> Awaitable[None]:
        """Set the amount of time that the script should wait during an
        execute_async_script call before throwing an error.

        :Args:
         - time_to_wait: The amount of time to wait (in seconds)

        :Usage:
            ::

                driver.set_script_timeout(30)
        """
        await self.execute(Command.SET_TIMEOUTS,
                {"script": int(float(time_to_wait) * 1000)})


    async def set_page_load_timeout(self, time_to_wait: float) -> Awaitable[None]:
        """Set the amount of time to wait for a page load to complete before
        throwing an error.

        :Args:
         - time_to_wait: The amount of time to wait

        :Usage:
            ::

                driver.set_page_load_timeout(30)
        """
        try:
            await self.execute(Command.SET_TIMEOUTS,
                    {"pageLoad": int(float(time_to_wait) * 1000)})
        except WebDriverException:
            await self.execute(Command.SET_TIMEOUTS,
                    {"ms": float(time_to_wait) * 1000, "type": "page load"})


    @property
    async def timeouts(self) -> Awaitable[Timeouts]:
        """Get all the timeouts that have been set on the current session.

        :Usage:
            ::

                driver.timeouts
        :rtype: Timeout
        """
        timeouts = (await self.execute(Command.GET_TIMEOUTS))["value"]
        timeouts["implicit_wait"] = timeouts.pop("implicit") / 1000
        timeouts["page_load"] = timeouts.pop("pageLoad") / 1000
        timeouts["script"] = timeouts.pop("script") / 1000
        return Timeouts(**timeouts)


    @timeouts.setter
    async def timeouts(self, timeouts) -> Awaitable[None]:
        """Set all timeouts for the session. This will override any previously
        set timeouts.

        :Usage:
            ::
                my_timeouts = Timeouts()
                my_timeouts.implicit_wait = 10
                driver.timeouts = my_timeouts
        """
        _ = (await self.execute(Command.SET_TIMEOUTS, timeouts._to_json())) \
                ["value"]


    async def find_element(self, by=By.ID, value: Optional[str] = None) \
            -> Awaitable[WebElement]:
        """Find an element given a By strategy and locator.

        :Usage:
            ::

                element = driver.find_element(By.ID, 'foo')

        :rtype: WebElement
        """
        if isinstance(by, RelativeBy):
            elements = await self.find_elements(by=by, value=value)
            if not elements:
                raise NoSuchElementException(
                        f"Cannot locate relative element with: {by.root}")
            return elements[0]

        if by == By.ID:
            by = By.CSS_SELECTOR
            value = f'[id="{value}"]'
        elif by == By.CLASS_NAME:
            by = By.CSS_SELECTOR
            value = f".{value}"
        elif by == By.NAME:
            by = By.CSS_SELECTOR
            value = f'[name="{value}"]'

        return (await self.execute(Command.FIND_ELEMENT,
                {"using": by, "value": value})) \
                ["value"]


    async def find_elements(self, by=By.ID, value: Optional[str] = None) \
            -> Awaitable[List[WebElement]]:
        """Find elements given a By strategy and locator.

        :Usage:
            ::

                elements = driver.find_elements(By.CLASS_NAME, 'foo')

        :rtype: list of WebElement
        """
        if isinstance(by, RelativeBy):
            _pkg = ".".join(__name__.split(".")[:-1])
            raw_function = pkgutil.get_data(_pkg, "findElements.js").decode("utf8")
            find_element_js = (
                f"/* findElements */return ({raw_function})"
                f".apply(null, arguments);"
            )
            return await self.execute_script(find_element_js, by.to_dict())

        if by == By.ID:
            by = By.CSS_SELECTOR
            value = f'[id="{value}"]'
        elif by == By.CLASS_NAME:
            by = By.CSS_SELECTOR
            value = f".{value}"
        elif by == By.NAME:
            by = By.CSS_SELECTOR
            value = f'[name="{value}"]'

        # Return empty list if driver returns null
        # See https://github.com/SeleniumHQ/selenium/issues/4555
        return (await self.execute(Command.FIND_ELEMENTS,
                {"using": by, "value": value})) \
                ["value"] or []


    @property
    def capabilities(self) -> dict:
        """Returns the drivers current capabilities being used."""
        return self.caps


    async def get_screenshot_as_file(self, filename) -> Awaitable[bool]:
        """Saves a screenshot of the current window to a PNG image file.
        Returns False if there is any IOError, else returns True. Use full
        paths in your filename.

        :Args:
         - filename: The full path you wish to save your screenshot to. This
           should end with a `.png` extension.

        :Usage:
            ::

                driver.get_screenshot_as_file('/Screenshots/foo.png')
        """
        if not str(filename).lower().endswith(".png"):
            warnings.warn(
                    "name used for saved screenshot does not match file type. "
                    "It should end with a `.png` extension",
                    UserWarning,
                    stacklevel=2)
        png = await self.get_screenshot_as_png()
        try:
            with open(filename, "wb") as f:
                f.write(png)
        except OSError:
            return False
        finally:
            del png
        return True


    async def save_screenshot(self, filename) -> Awaitable[bool]:
        """Saves a screenshot of the current window to a PNG image file.
        Returns False if there is any IOError, else returns True. Use full
        paths in your filename.

        :Args:
         - filename: The full path you wish to save your screenshot to. This
           should end with a `.png` extension.

        :Usage:
            ::

                driver.save_screenshot('/Screenshots/foo.png')
        """
        return await self.get_screenshot_as_file(filename)


    async def get_screenshot_as_png(self) -> Awaitable[bytes]:
        """Gets the screenshot of the current window as a binary data.

        :Usage:
            ::

                driver.get_screenshot_as_png()
        """
        return b64decode((await self.get_screenshot_as_base64()).encode("ascii"))


    async def get_screenshot_as_base64(self) -> Awaitable[str]:
        """Gets the screenshot of the current window as a base64 encoded string
        which is useful in embedded images in HTML.

        :Usage:
            ::

                driver.get_screenshot_as_base64()
        """
        return (await self.execute(Command.SCREENSHOT))["value"]


    async def set_window_size(self, width, height, windowHandle: str = "current") \
            -> Awaitable[None]:
        """Sets the width and height of the current window. (window.resizeTo)

        :Args:
         - width: the width in pixels to set the window to
         - height: the height in pixels to set the window to

        :Usage:
            ::

                driver.set_window_size(800,600)
        """
        self._check_if_window_handle_is_current(windowHandle)
        await self.set_window_rect(width=int(width), height=int(height))


    async def get_window_size(self, windowHandle: str = "current") \
            -> Awaitable[dict]:
        """Gets the width and height of the current window.

        :Usage:
            ::

                driver.get_window_size()
        """

        self._check_if_window_handle_is_current(windowHandle)
        size = await self.get_window_rect()

        if size.get("value", None):
            size = size["value"]

        return {k: size[k] for k in ("width", "height")}


    async def set_window_position(self, x: float, y: float,
            windowHandle: str = "current") \
            -> Awaitable[dict]:
        """Sets the x,y position of the current window. (window.moveTo)

        :Args:
         - x: the x-coordinate in pixels to set the window position
         - y: the y-coordinate in pixels to set the window position

        :Usage:
            ::

                driver.set_window_position(0,0)
        """
        self._check_if_window_handle_is_current(windowHandle)
        return await self.set_window_rect(x=int(x), y=int(y))


    async def get_window_position(self, windowHandle="current") -> Awaitable[dict]:
        """Gets the x,y position of the current window.

        :Usage:
            ::

                driver.get_window_position()
        """

        self._check_if_window_handle_is_current(windowHandle)
        position = await self.get_window_rect()

        return {k: position[k] for k in ("x", "y")}


    def _check_if_window_handle_is_current(self, windowHandle: str) -> None:
        """Warns if the window handle is not equal to `current`."""
        if windowHandle != "current":
            warnings.warn(
                    "Only 'current' window is supported for W3C compatible "
                    "browsers.",
                    stacklevel=2)


    async def get_window_rect(self) -> Awaitable[dict]:
        """Gets the x, y coordinates of the window as well as height and width
        of the current window.

        :Usage:
            ::

                driver.get_window_rect()
        """
        return (await self.execute(Command.GET_WINDOW_RECT))["value"]


    async def set_window_rect(self, x=None, y=None, width=None, height=None) \
            -> Awaitable[dict]:
        """Sets the x, y coordinates of the window as well as height and width
        of the current window. This method is only supported for W3C compatible
        browsers; other browsers should use `set_window_position` and
        `set_window_size`.

        :Usage:
            ::

                driver.set_window_rect(x=10, y=10)
                driver.set_window_rect(width=100, height=200)
                driver.set_window_rect(x=10, y=10, width=100, height=200)
        """

        if (x is None and y is None) and (not height and not width):
            raise InvalidArgumentException(
                    "x and y or height and width need values")

        return (await self.execute(Command.SET_WINDOW_RECT,
                {"x": x, "y": y, "width": width, "height": height})) \
                ["value"]


    @property
    def file_detector(self) -> FileDetector:
        return self._file_detector


    @file_detector.setter
    def file_detector(self, detector) -> None:
        """Set the file detector to be used when sending keyboard input. By
        default, this is set to a file detector that does nothing.

        see FileDetector
        see LocalFileDetector
        see UselessFileDetector

        :Args:
         - detector: The detector to use. Must not be None.
        """
        if not detector:
            raise WebDriverException("You may not set a file detector that is null")
        if not isinstance(detector, FileDetector):
            raise WebDriverException("Detector has to be instance of FileDetector")
        self._file_detector = detector


    @property
    async def orientation(self):
        """Gets the current orientation of the device.

        :Usage:
            ::

                orientation = driver.orientation
        """
        return (await self.execute(Command.GET_SCREEN_ORIENTATION))["value"]


    @orientation.setter
    async def orientation(self, value) -> Awaitable[None]:
        """Sets the current orientation of the device.

        :Args:
         - value: orientation to set it to.

        :Usage:
            ::

                driver.orientation = 'landscape'
        """
        allowed_values = ["LANDSCAPE", "PORTRAIT"]
        if value.upper() in allowed_values:
            await self.execute(Command.SET_SCREEN_ORIENTATION,
                    {"orientation": value})
        else:
            raise WebDriverException(
                    "You can only set the orientation to 'LANDSCAPE' and 'PORTRAIT'")


    @property
    async def log_types(self):
        """Gets a list of the available log types. This only works with w3c
        compliant browsers.

        :Usage:
            ::

                driver.log_types
        """
        return (await self.execute(Command.GET_AVAILABLE_LOG_TYPES))["value"]


    async def get_log(self, log_type):
        """Gets the log for a given log type.

        :Args:
         - log_type: type of log that which will be returned

        :Usage:
            ::

                driver.get_log('browser')
                driver.get_log('driver')
                driver.get_log('client')
                driver.get_log('server')
        """
        return (await self.execute(Command.GET_LOG, {"type": log_type}))["value"]


    @asynccontextmanager
    async def bidi_connection(self):
        webdriver.import_cdp()
        if self.caps.get("se:cdp"):
            ws_url = self.caps.get("se:cdp")
            version = self.caps.get("se:cdpVersion").split(".")[0]
        else:
            version, ws_url = self._get_cdp_details()

        if not ws_url:
            raise WebDriverException(
                    "Unable to find url to connect to from capabilities")

        devtools = webdriver.cdp.import_devtools(version)
        async with webdriver.cdp.open_cdp(ws_url) as conn:
            targets = await conn.execute(devtools.target.get_targets())
            target_id = targets[0].target_id
            async with conn.open_session(target_id) as session:
                yield BidiConnection(session, webdriver.cdp, devtools)


    def _get_cdp_details(self):
        import json

        import urllib3

        http = urllib3.PoolManager()
        _firefox = False
        if self.caps.get("browserName") == "chrome":
            debugger_address = self.caps.get("goog:chromeOptions") \
                    .get("debuggerAddress")
        elif self.caps.get("browserName") == "MicrosoftEdge":
            debugger_address = self.caps.get("ms:edgeOptions") \
                    .get("debuggerAddress")
        else:
            _firefox = True
            debugger_address = self.caps.get("moz:debuggerAddress")
        res = http.request("GET", f"http://{debugger_address}/json/version")
        data = json.loads(res.data)

        browser_version = data.get("Browser")
        websocket_url = data.get("webSocketDebuggerUrl")

        import re

        if _firefox:
            # Mozilla Automation Team asked to only support 85
            # until WebDriver Bidi is available.
            version = 85
        else:
            version = re.search(r".*/(\d+)\.", browser_version).group(1)

        return version, websocket_url


    # Virtual Authenticator Methods
    async def add_virtual_authenticator(self,
            options: VirtualAuthenticatorOptions) \
            -> Awaitable[None]:
        """Adds a virtual authenticator with the given options."""
        self._authenticator_id = (await self.execute(
                Command.ADD_VIRTUAL_AUTHENTICATOR, options.to_dict())) \
                ["value"]


    @property
    def virtual_authenticator_id(self) -> str:
        """Returns the id of the virtual authenticator."""
        return self._authenticator_id


    @required_virtual_authenticator
    async def remove_virtual_authenticator(self) -> Awaitable[None]:
        """Removes a previously added virtual authenticator.

        The authenticator is no longer valid after removal, so no
        methods may be called.
        """
        await self.execute(Command.REMOVE_VIRTUAL_AUTHENTICATOR,
                {"authenticatorId": self._authenticator_id})
        self._authenticator_id = None


    @required_virtual_authenticator
    async def add_credential(self, credential: Credential) -> Awaitable[None]:
        """Injects a credential into the authenticator."""
        await self.execute(Command.ADD_CREDENTIAL,
                {
                    **credential.to_dict(),
                    "authenticatorId": self._authenticator_id,
                })


    @required_virtual_authenticator
    async def get_credentials(self) -> Awaitable[List[Credential]]:
        """Returns the list of credentials owned by the authenticator."""
        credential_data = await self.execute(Command.GET_CREDENTIALS,
                {"authenticatorId": self._authenticator_id})
        return [Credential.from_dict(credential) \
                for credential in credential_data["value"]]


    @required_virtual_authenticator
    async def remove_credential(self, credential_id: Union[str, bytearray]) \
            -> Awaitable[None]:
        """Removes a credential from the authenticator."""
        # Check if the credential is bytearray converted to b64 string
        if isinstance(credential_id, bytearray):
            credential_id = urlsafe_b64encode(credential_id).decode()

        await self.execute(Command.REMOVE_CREDENTIAL,
                {
                    "credentialId": credential_id,
                    "authenticatorId": self._authenticator_id,
                })


    @required_virtual_authenticator
    async def remove_all_credentials(self) -> Awaitable[None]:
        """Removes all credentials from the authenticator."""
        await self.execute(Command.REMOVE_ALL_CREDENTIALS,
                {"authenticatorId": self._authenticator_id})


    @required_virtual_authenticator
    async def set_user_verified(self, verified: bool) -> Awaitable[None]:
        """Sets whether the authenticator will simulate success or fail on user
        verification.

        verified: True if the authenticator will pass user verification,
            False otherwise.
        """
        await self.execute(Command.SET_USER_VERIFIED,
                {
                    "authenticatorId": self._authenticator_id,
                    "isUserVerified": verified,
                })


    async def get_downloadable_files(self) -> Awaitable[dict]:
        """Retrieves the downloadable files as a map of file names and their
        corresponding URLs."""
        if "se:downloadsEnabled" not in self.capabilities:
            raise WebDriverException(
                    "You must enable downloads in order to work with "
                    "downloadable files.")

        return (await self.execute(Command.GET_DOWNLOADABLE_FILES)) \
                ["value"]["names"]


    async def download_file(self, file_name: str, target_directory: str) \
            -> Awaitable[None]:
        """Downloads a file with the specified file name to the target
        directory.

        file_name: The name of the file to download.
        target_directory: The path to the directory to save the downloaded file.
        """
        if "se:downloadsEnabled" not in self.capabilities:
            raise WebDriverException(
                    "You must enable downloads in order to work with "
                    "downloadable files.")

        if not os.path.exists(target_directory):
            os.makedirs(target_directory)

        contents = (await self.execute(Command.DOWNLOAD_FILE,
                {"name": file_name})) \
                ["value"]["contents"]

        target_file = os.path.join(target_directory, file_name)
        with open(target_file, "wb") as file:
            file.write(b64decode(contents))

        with zipfile.ZipFile(target_file, "r") as zip_ref:
            zip_ref.extractall(target_directory)


    async def delete_downloadable_files(self) -> Awaitable[None]:
        """Deletes all downloadable files."""
        if "se:downloadsEnabled" not in self.capabilities:
            raise WebDriverException(
                    "You must enable downloads in order to work with "
                    "downloadable files.")

        await self.execute(Command.DELETE_DOWNLOADABLE_FILES)
