import asyncio
from asyncio.subprocess import PIPE
from decimal import Decimal
import logging
from subprocess import CalledProcessError


class Marinade:

    def __init__(
            self,
            config_file: str,
            key_file: str,
            executable: str = 'marinade',
    ):
        self._executable = executable
        self._config_file = config_file
        self._key_file = key_file
        # The profile needs to looks something like this:
        # json_rpc_url: "https://api.mainnet-beta.solana.com"
        # websocket_url: "wss://api.mainnet-beta.solana.com/"
        # keypair_path: "/path/to/private/key.json"
        # commitment: "confirmed"
        # TODO: Maybe it should be rather generated on the fly for more convenience

        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    async def stake(self, amount: Decimal):
        self.logger.info('Going to stake - prep args', extra=dict(amount=amount))
        args = [
            *(['-c', self._config_file] if self._config_file is not None else []),
            'stake',
            *(['-f', self._key_file] if self._key_file is not None else []),
            str(amount),
        ]
        self.logger.info(
            'Going to stake - calling subprocess',
            extra=dict(amount=amount, args=args)
        )
        proc = await asyncio.create_subprocess_exec(
            self._executable, *args,
            stderr=PIPE, stdout=PIPE,
        )
        (stdout, stderr) = await proc.communicate(None)
        self.logger.info(
            'Going to stake - finished',
            extra=dict(returncode=proc.returncode, cmd=args, output=stdout, stderr=stderr)
        )
        if proc.returncode != 0:
            raise CalledProcessError(
                returncode=proc.returncode, cmd=args, output=stdout, stderr=stderr
            )
