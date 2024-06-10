from io import BytesIO
import os
from typing import Awaitable, List, Self
import warnings
import zipfile
#-
from selenium.common.exceptions import JavascriptException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.utils import keys_to_typing
from selenium.webdriver.remote import webelement
from selenium.webdriver.remote.command import Command
#-
from .shadowroot import ShadowRoot

class WebElement(webelement.BaseWebElement):
    """Represents a DOM element.

    Generally, all interesting operations that interact with a document will be
    performed through this interface.

    All method calls will do a freshness check to ensure that the element
    reference is still valid.  This essentially determines whether the
    element is still attached to the DOM.  If this test fails, then an
    ``StaleElementReferenceException`` is thrown, and all future calls to this
    instance will fail.
    """

    def __init__(self, parent, id_) -> None:
        self._parent = parent
        self._id = id_


    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} (session="{self._parent.session_id}", element="{self._id}")>'


    @property
    async def tag_name(self) -> Awaitable[str]:
        """This element's ``tagName`` property."""
        return (await self._execute(Command.GET_ELEMENT_TAG_NAME))['value']


    @property
    async def text(self) -> Awaitable[str]:
        """The text of the element."""
        return (await self._execute(Command.GET_ELEMENT_TEXT))["value"]


    async def click(self) -> Awaitable[None]:
        """Clicks the element."""
        await self._execute(Command.CLICK_ELEMENT)


    async def submit(self) -> Awaitable[None]:
        """Submits a form."""
        script = (
            "/* submitForm */var form = arguments[0];\n"
            'while (form.nodeName != "FORM" && form.parentNode) {\n'
            "  form = form.parentNode;\n"
            "}\n"
            "if (!form) { throw Error('Unable to find containing form element'); }\n"
            "if (!form.ownerDocument) { throw Error('Unable to find owning document'); }\n"
            "var e = form.ownerDocument.createEvent('Event');\n"
            "e.initEvent('submit', true, true);\n"
            "if (form.dispatchEvent(e)) { HTMLFormElement.prototype.submit.call(form) }\n"
        )

        try:
            await self._parent.execute_script(script, self)
        except JavascriptException as exc:
            raise WebDriverException(
                    "To submit an element, it must be nested inside a form "
                    "element") \
                    from exc


    async def clear(self) -> Awaitable[None]:
        """Clears the text if it's a text entry element."""
        await self._execute(Command.CLEAR_ELEMENT)


    async def get_property(self, name) -> Awaitable[str | bool | Self | dict]:
        """Gets the given property of the element.

        :Args:
            - name - Name of the property to retrieve.

        :Usage:
            ::

                text_length = target_element.get_property("text_length")
        """
        try:
            return (await self._execute(Command.GET_ELEMENT_PROPERTY,
                    {"name": name})) \
                    ["value"]
        except WebDriverException:
            # if we hit an end point that doesn't understand getElementProperty
            # lets fake it
            return await self.parent.execute_script(
                    "return arguments[0][arguments[1]]", self, name)


    async def get_dom_attribute(self, name) -> Awaitable[str]:
        """Gets the given attribute of the element. Unlike
        :func:`~selenium.webdriver.remote.BaseWebElement.get_attribute`, this
        method only returns attributes declared in the element's HTML markup.

        :Args:
            - name - Name of the attribute to retrieve.

        :Usage:
            ::

                text_length = target_element.get_dom_attribute("class")
        """
        return (await self._execute(Command.GET_ELEMENT_ATTRIBUTE,
                {"name": name})) \
                ["value"]


    async def get_attribute(self, name) -> Awaitable[str | None]:
        """Gets the given attribute or property of the element.

        This method will first try to return the value of a property with the
        given name. If a property with that name doesn't exist, it returns the
        value of the attribute with the same name. If there's no attribute with
        that name, ``None`` is returned.

        Values which are considered truthy, that is equals "true" or "false",
        are returned as booleans.  All other non-``None`` values are returned
        as strings.  For attributes or properties which do not exist, ``None``
        is returned.

        To obtain the exact value of the attribute or property,
        use :func:`~selenium.webdriver.remote.BaseWebElement.get_dom_attribute` or
        :func:`~selenium.webdriver.remote.BaseWebElement.get_property` methods respectively.

        :Args:
            - name - Name of the attribute/property to retrieve.

        Example::

            # Check if the "active" CSS class is applied to an element.
            is_active = "active" in target_element.get_attribute("class")
        """
        if webelement.getAttribute_js is None:
            webelement._load_js()
        script = (
            "/* getAttribute */return "
            f"({webelement.getAttribute_js}).apply(null, arguments);"
        )
        attribute_value = await self.parent.execute_script(script, self, name)
        return attribute_value


    async def is_selected(self) -> Awaitable[bool]:
        """Returns whether the element is selected.

        Can be used to check if a checkbox or radio button is selected.
        """
        return (await self._execute(Command.IS_ELEMENT_SELECTED))["value"]


    async def is_enabled(self) -> Awaitable[bool]:
        """Returns whether the element is enabled."""
        return (await self._execute(Command.IS_ELEMENT_ENABLED))["value"]


    async def send_keys(self, *value: str) -> Awaitable[None]:
        """Simulates typing into the element.

        :Args:
            - value - A string for typing, or setting form fields.  For setting
              file inputs, this could be a local file path.

        Use this to send simple key events or to fill out form fields::

            form_textfield = driver.find_element(By.NAME, 'username')
            form_textfield.send_keys("admin")

        This can also be used to set file inputs.

        ::

            file_input = driver.find_element(By.NAME, 'profilePic')
            file_input.send_keys("path/to/profilepic.gif")
            # Generally it's better to wrap the file path in one of the methods
            # in os.path to return the actual path to support cross OS testing.
            # file_input.send_keys(os.path.abspath("path/to/profilepic.gif"))
        """
        # transfer file to another machine only if remote driver is used
        # the same behaviour as for java binding
        if self.parent._is_remote:
            local_files = list(
                map(
                    lambda keys_to_send: self.parent.file_detector.is_local_file(
                        str(keys_to_send)),
                    "".join(map(str, value)).split("\n"),
                )
            )
            if None not in local_files:
                remote_files = []
                for file in local_files:
                    remote_files.append(await self._upload(file))
                value = "\n".join(remote_files)

        await self._execute(Command.SEND_KEYS_TO_ELEMENT,
                {
                    "text": "".join(keys_to_typing(value)),
                    "value": keys_to_typing(value),
                })


    @property
    async def shadow_root(self) -> Awaitable[ShadowRoot]:
        """Returns a shadow root of the element if there is one or an error.
        Only works from Chromium 96, Firefox 96, and Safari 16.4 onwards.

        :Returns:
          - ShadowRoot object or
          - NoSuchShadowRoot - if no shadow root was attached to element
        """
        return (await self._execute(Command.GET_SHADOW_ROOT))["value"]


    # RenderedWebElement Items
    async def is_displayed(self) -> Awaitable[bool]:
        """Whether the element is visible to a user."""
        # Only go into this conditional for browsers that don't use the atom
        # themselves
        if webelement.isDisplayed_js is None:
            webelement._load_js()
        script = (
            "/* isDisplayed */return "
            f"({webelement.isDisplayed_js}).apply(null, arguments);"
        )
        return await self.parent.execute_script(script, self)


    @property
    async def location_once_scrolled_into_view(self) -> Awaitable[dict]:
        """THIS PROPERTY MAY CHANGE WITHOUT WARNING. Use this to discover where
        on the screen an element is so that we can click it. This method should
        cause the element to be scrolled into view.

        Returns the top lefthand corner location on the screen, or zero
        coordinates if the element is not visible.
        """
        script = (
            "arguments[0].scrollIntoView(true); return "
            "arguments[0].getBoundingClientRect()"
        )
        old_loc = (await self._execute(Command.W3C_EXECUTE_SCRIPT,
                {
                    "script": script,
                    "args": [self],
                })) \
                ["value"]
        return {"x": round(old_loc["x"]), "y": round(old_loc["y"])}


    @property
    async def size(self) -> Awaitable[dict]:
        """The size of the element."""
        size = (await self._execute(Command.GET_ELEMENT_RECT))["value"]
        new_size = {"height": size["height"], "width": size["width"]}
        return new_size


    async def value_of_css_property(self, property_name) -> Awaitable[str]:
        """The value of a CSS property."""
        return (await self._execute(Command.GET_ELEMENT_VALUE_OF_CSS_PROPERTY,
                {"propertyName": property_name})) \
                ["value"]


    @property
    async def location(self) -> Awaitable[dict]:
        """The location of the element in the renderable canvas."""
        old_loc = (await self._execute(Command.GET_ELEMENT_RECT))["value"]
        new_loc = {"x": round(old_loc["x"]), "y": round(old_loc["y"])}
        return new_loc


    @property
    async def rect(self) -> Awaitable[dict]:
        """A dictionary with the size and location of the element."""
        return (await self._execute(Command.GET_ELEMENT_RECT))["value"]


    @property
    async def aria_role(self) -> Awaitable[str]:
        """Returns the ARIA role of the current web element."""
        return (await self._execute(Command.GET_ELEMENT_ARIA_ROLE))["value"]


    @property
    async def accessible_name(self) -> Awaitable[str]:
        """Returns the ARIA Level of the current webelement."""
        return (await self._execute(Command.GET_ELEMENT_ARIA_LABEL))["value"]


    @property
    async def screenshot_as_base64(self) -> Awaitable[str]:
        """Gets the screenshot of the current element as a base64 encoded
        string.

        :Usage:
            ::

                img_b64 = element.screenshot_as_base64
        """
        return (await self._execute(Command.ELEMENT_SCREENSHOT))["value"]


    @property
    async def screenshot_as_png(self) -> Awaitable[bytes]:
        """Gets the screenshot of the current element as a binary data.

        :Usage:
            ::

                element_png = element.screenshot_as_png
        """
        return b64decode((await self.screenshot_as_base64).encode("ascii"))


    async def screenshot(self, filename) -> Awaitable[bool]:
        """Saves a screenshot of the current element to a PNG image file.
        Returns False if there is any IOError, else returns True. Use full
        paths in your filename.

        :Args:
         - filename: The full path you wish to save your screenshot to. This
           should end with a `.png` extension.

        :Usage:
            ::

                element.screenshot('/Screenshots/foo.png')
        """
        if not filename.lower().endswith(".png"):
            warnings.warn(
                    "name used for saved screenshot does not match file type. It "
                    "should end with a `.png` extension",
                    UserWarning)
        png = await self.screenshot_as_png
        try:
            with open(filename, "wb") as f:
                f.write(png)
        except OSError:
            return False
        finally:
            del png
        return True


    @property
    def parent(self):
        """Internal reference to the WebDriver instance this element was found
        from."""
        return self._parent


    @property
    def id(self) -> str:
        """Internal ID used by selenium.

        This is mainly for internal use. Simple use cases such as checking if 2
        webelements refer to the same element, can be done using ``==``::

            if element1 == element2:
                print("These 2 are equal")
        """
        return self._id


    def __eq__(self, element):
        return hasattr(element, "id") and self._id == element.id


    def __ne__(self, element):
        return not self.__eq__(element)


    # Private Methods
    async def _execute(self, command, params=None):
        """Executes a command against the underlying HTML element.

        Args:
          command: The name of the command to _execute as a string.
          params: A dictionary of named parameters to send with the command.

        Returns:
          The command's JSON response loaded into a dictionary object.
        """
        if not params:
            params = {}
        params["id"] = self._id
        return await self._parent.execute(command, params)


    async def find_element(self, by=By.ID, value=None) -> Awaitable[Self]:
        """Find an element given a By strategy and locator.

        :Usage:
            ::

                element = element.find_element(By.ID, 'foo')

        :rtype: WebElement
        """
        if by == By.ID:
            by = By.CSS_SELECTOR
            value = f'[id="{value}"]'
        elif by == By.CLASS_NAME:
            by = By.CSS_SELECTOR
            value = f".{value}"
        elif by == By.NAME:
            by = By.CSS_SELECTOR
            value = f'[name="{value}"]'

        return (await self._execute(Command.FIND_CHILD_ELEMENT,
                {"using": by, "value": value})) \
                ["value"]


    async def find_elements(self, by=By.ID, value=None) -> Awaitable[List[Self]]:
        """Find elements given a By strategy and locator.

        :Usage:
            ::

                element = element.find_elements(By.CLASS_NAME, 'foo')

        :rtype: list of WebElement
        """
        if by == By.ID:
            by = By.CSS_SELECTOR
            value = f'[id="{value}"]'
        elif by == By.CLASS_NAME:
            by = By.CSS_SELECTOR
            value = f".{value}"
        elif by == By.NAME:
            by = By.CSS_SELECTOR
            value = f'[name="{value}"]'

        return (await self._execute(Command.FIND_CHILD_ELEMENTS,
                {"using": by, "value": value})) \
                ["value"]


    def __hash__(self) -> int:
        return int(md5_hash(self._id.encode("utf-8")).hexdigest(), 16)


    async def _upload(self, filename):
        fp = BytesIO()
        zipped = zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED)
        zipped.write(filename, os.path.split(filename)[1])
        zipped.close()
        content = encodebytes(fp.getvalue())
        if not isinstance(content, str):
            content = content.decode("utf-8")
        try:
            return (await self._execute(Command.UPLOAD_FILE, {"file": content})) \
                    ["value"]
        except WebDriverException as e:
            if "Unrecognized command: POST" in str(e):
                return filename
            if "Command not found: POST " in str(e):
                return filename
            if '{"status":405,"value":["GET","HEAD","DELETE"]}' in str(e):
                return filename
            raise
