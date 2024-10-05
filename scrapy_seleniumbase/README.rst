==========================================================
scrapy-seleniumbase: Selenium Grid integration for Scrapy
==========================================================

A Scrapy_ Download Handler which performs requests using `Selenium Grid`_
(aiohttp_). It can be used to handle pages that require JavaScript (among other
things), while adhering to the regular Scrapy workflow (i.e. without interfering
with request scheduling, item processing, etc).

This is unofficial scrapy plugin and unofficial selenium scrapy plugin.

The development of this module is heavily inspired by `scrapy-playwright`_ and
`asyncselenium`_.


Requirements
============

After the release of `version 2.0 <Scrapy_v2_>`__, which includes `coroutine syntax
support <ScrapyCoroutineSyntax_>`__ and `asyncio support <ScrapyAsyncioSupport_>`__,
Scrapy allows to integrate :code:`asyncio`-based projects such as aiohttp_.


Minimum required versions
-------------------------

* Python >= 3.8
* Scrapy >= 2.0
* aiohttp


Installation
============

:code:`scrapy-seleniumbase` is available on PyPI and can be installed with
:code:`pip`:

.. code-block:: sh

  pip install scrapy-seleniumbase


Activation
==========

Replace the default :code:`http` and/or :code:`https` Download Handlers through
`DOWNLOAD_HANDLERS <ScrapySettings_>`__:

.. code-block:: python

  DOWNLOAD_HANDLERS = {
      'http': 'scrapy_seleniumbase.download_handler.ScrapyDownloadHandler',
      'https': 'scrapy_seleniumbase.download_handler.ScrapyDownloadHandler',
  }

Note that the :code:`ScrapyDownloadHandler` class inherits from the default
:code:`http/https` handler. Unless explicitly marked (see `Basic Usage`_),
requests will be processed by the regular Scrapy download handler.

Also, be sure to `install the asyncio-based Twisted reactor
<ScrapyAsyncioReactor_>`__:

.. code-block:: python

  TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'


.. _Basic Usage:

Basic Usage
===========

Set the `seleniumbase <ScrapyRequestMeta_>`__ key to download a request using
Selenium Grid:

.. code-block:: python

  import scrapy

  class AwesomeSpider(scrapy.Spider):
      name = "awesome"

      def start_requests(self):
          # GET request
          yield scrapy.Request("https://httpbin.org/get", meta={"seleniumbase": True})
          # POST request
          yield scrapy.FormRequest(
              url="https://httpbin.org/post",
              formdata={"foo": "bar"},
              meta={"seleniumbase": True},
          )

      def parse(self, response, **kwargs):
          # 'response' contains the page as seen by the browser
          return {"url": response.url}


Supported Settings
==================

SELENIUMBASE_BROWSER_NAME
--------------------------

Type :code:`str`, default :code:`chrome`

The browser type to be used in Selenium Grid, e.g. :code:`chrome`, :code:`edge`,
:code:`firefox`, :code:`ie`, :code:`safari`.


SELENIUMBASE_URL
-----------------

Type :code:`str`, default :code:`http://127.0.0.1:4444`

The Selenium Grid hub url.


SELENIUMBASE_IMPLICIT_WAIT_INSEC
---------------------------------

Type :code:`int`, default :code:`0`

Selenium has a built-in way to `automatically wait for elements
<SeleniumImplicitWaits_>`__.

This is a global setting that applies to every element location call for the entire
session. The default value is 0, which means that if the element is not found, it
will immediately return an error. If an implicit wait is set, the driver will wait
for the duration of the provided value before returning the error. Note that as
soon as the element is located, the driver will return the element reference and
the code will continue executing, so a larger implicit wait value won’t necessarily
increase the duration of the session.


Supported Request Meta
======================

seleniumbase
-------------

Type :code:`bool`, default :code:`False`

If set to a value that evaluates to :code:`True` the request will be processed by
Selenium Grid.

.. code-block:: python

  return scrapy.Request("https://example.org", meta={"seleniumbase": True})


seleniumbase_driver
--------------------

Type :code:`scrapy_seleniumbase.webdriver.WebDriver`

This will be set with asynchronous Selenium Driver when you enabled seleniumbase
in request meta.

.. code-block:: python

  import scrapy
  from scrapy_seleniumbase.common.action_chains import ActionChains
  from selenium.webdriver.common.by import By
  from selenium.webdriver.common.keys import Keys

  def start_requests(self):
      yield scrapy.Request(
          url="https://httpbin.org/get",
          meta={"seleniumbase": True},
      )
  
  async def parse(self, response, **kwargs):
      driver = response.meta["seleniumbase_driver"]

      await ActionChains(driver).key_down(Keys.F12).key_up(Keys.F12).perform()

      inp_userid = await driver.find_element(By.CSS_SELECTOR, 'input[name="userid"]')
      assert await inp_userid.is_displayed() == True
      await inp_userid.send_keys("Username")

      print(await driver.get_log('browser'))


seleniumbase_browser
---------------------

Type :code:`str`, default :code:`None`

Same values as :code:`SELENIUMBASE_BROWSER_NAME` but you set it per request.



.. _Scrapy: https://github.com/scrapy/scrapy
.. _ScrapyAsyncioReactor: https://docs.scrapy.org/en/latest/topics/asyncio.html#installing-the-asyncio-reactor
.. _ScrapyAsyncioSupport: https://docs.scrapy.org/en/2.0/topics/asyncio.html
.. _ScrapyCoroutineSyntax: https://docs.scrapy.org/en/2.0/topics/coroutines.html
.. _ScrapyRequestMeta: https://docs.scrapy.org/en/latest/topics/request-response.html#scrapy.http.Request.meta
.. _ScrapySettings: https://docs.scrapy.org/en/latest/topics/settings.html
.. _Scrapy_v2: https://docs.scrapy.org/en/latest/news.html#scrapy-2-0-0-2020-03-03
.. _Selenium Grid: https://www.selenium.dev/documentation/grid/
.. _SeleniumImplicitWaits: https://www.selenium.dev/documentation/webdriver/waits/#implicit-waits
.. _aiohttp: https://github.com/aio-libs/aiohttp
.. _scrapy-playwright: https://github.com/scrapy-plugins/scrapy-playwright
.. _asyncselenium: https://github.com/Yyonging/asyncselenium
