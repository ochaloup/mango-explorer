import asyncio
import os
import traceback


def wrap_main(main):
    # noinspection PyBroadException
    try:
        main()
    except BaseException:
        print("main thread failed")
        traceback.print_exc()
        # I would prefer calling sys.exit(42), but it doesn't exit until other threads do so
        os.execl("/bin/bash", 'bash', '-c', 'exit 42')


def wrap_async_main(main):
    wrap_main(lambda: asyncio.run(main()))
