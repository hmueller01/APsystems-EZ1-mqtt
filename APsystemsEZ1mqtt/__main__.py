"""This is the entry point of the script and it runs the main function in an asynchronous manner."""
import asyncio
from APsystemsEZ1mqtt.main import main

# Run the main coroutine.
asyncio.run(main())
