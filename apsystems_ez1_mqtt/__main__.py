"""This is the entry point of the script and it runs the main function in an asynchronous manner."""
import asyncio
from apsystems_ez1_mqtt.main import main

# Run the main coroutine.
asyncio.run(main())
